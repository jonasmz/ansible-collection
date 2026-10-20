#!/usr/bin/perl
# SPDX-License-Identifier: MIT-0
# Standalone helper that adds a Koha SMTP server and makes it the default.
# It never touches koha-conf.xml or the system default server Koha ships with.
use strict;
use warnings;
use JSON::PP qw(decode_json encode_json);

my $PROTOCOL = 1;
my @FIELDS = qw(host port timeout ssl_mode user_name password debug);

sub emit {
    my ($payload) = @_;
    print STDOUT encode_json($payload), "\n";
}

sub snapshot {
    my ($server) = @_;
    return {
        name      => $server->name,
        host      => $server->host,
        port      => 0 + $server->port,
        timeout   => 0 + $server->timeout,
        ssl_mode  => $server->ssl_mode,
        user_name => $server->user_name // '',
        password  => $server->password // '',
        debug     => $server->debug ? 1 : 0,
    };
}

# Report state without the secret: only whether a password is stored.
sub public_view {
    my ($state, $is_default) = @_;
    return undef unless $state;
    my %view = %{$state};
    $view{password} = length($view{password}) ? JSON::PP::true : JSON::PP::false;
    $view{debug} = $view{debug} ? JSON::PP::true : JSON::PP::false;
    $view{is_default} = $is_default ? JSON::PP::true : JSON::PP::false;
    return \%view;
}

sub differs {
    my ($current, $wanted) = @_;
    for my $field (@FIELDS) {
        return 1 if "$current->{$field}" ne "$wanted->{$field}";
    }
    return 0;
}

sub run {
    my ($request) = @_;
    die "Unsupported protocol version" unless ref($request) eq 'HASH' && $request->{protocol} == $PROTOCOL;
    die "Unsupported operation" unless ($request->{operation} // '') eq 'configure';
    my $desired = $request->{desired};
    die "desired configuration must be an object" unless ref($desired) eq 'HASH';
    die "apply must be a boolean" unless defined $request->{apply} && ($request->{apply} == 0 || $request->{apply} == 1);

    require C4::Context;
    require Koha::Database;
    require Koha::SMTP::Servers;
    require Koha::SMTP::Server;

    my $context = C4::Context->new;
    $context->set_context;
    die "Koha is not initialized: run initialize before smtp" if C4::Context->needs_install;

    my $schema = Koha::Database->new->schema;
    die "This Koha version cannot store a default SMTP server (smtp_servers.is_default is absent)"
        unless $schema->resultset('SmtpServer')->result_source->has_column('is_default');

    my $name = $desired->{name};
    my %wanted = map { $_ => $desired->{$_} } @FIELDS;

    my @matches = Koha::SMTP::Servers->search({ name => $name })->as_list;
    die "More than one SMTP server is named '$name'; rename the duplicates first" if @matches > 1;
    my $server = $matches[0];
    my @defaults = Koha::SMTP::Servers->search({ is_default => 1 })->as_list;
    my @others = grep { !$server || $_->id != $server->id } @defaults;

    my $before = $server ? snapshot($server) : undef;
    my $was_default = $server && $server->is_default ? 1 : 0;
    my $create = !$server;
    my $update = $server && differs($before, \%wanted);
    my $promote = !$was_default;
    my $changed = $create || $update || $promote;

    if ($request->{apply} && $changed) {
        $schema->txn_do(sub {
            if ($create) {
                $server = Koha::SMTP::Server->new({ name => $name, %wanted, is_default => 0 })->store;
            } elsif ($update) {
                $server->set(\%wanted)->store;
            }
            # Only one default may exist: demote the previous one, never edit or delete it.
            for my $other (@others) {
                $other->set({ is_default => 0 })->store;
            }
            $server->set({ is_default => 1 })->store;
        });
        $server = Koha::SMTP::Servers->find($server->id);
        die "Koha did not retain the SMTP server" unless $server;
        my $actual = snapshot($server);
        die "Koha did not retain the requested SMTP server values" if differs($actual, \%wanted);
        my @now = Koha::SMTP::Servers->search({ is_default => 1 })->as_list;
        die "Koha did not leave '$name' as the only default SMTP server"
            unless @now == 1 && $now[0]->id == $server->id;
    }

    my $after = $request->{apply} && $changed ? snapshot($server) : { name => $name, %wanted };
    return {
        protocol => $PROTOCOL, ok => JSON::PP::true,
        changed => $changed ? JSON::PP::true : JSON::PP::false,
        created => $create ? JSON::PP::true : JSON::PP::false,
        updated => $update ? JSON::PP::true : JSON::PP::false,
        promoted => $promote ? JSON::PP::true : JSON::PP::false,
        server_id => $server ? 0 + $server->id : undef,
        previous_default => @others ? { id => 0 + $others[0]->id, name => $others[0]->name } : undef,
        before => public_view($before, $was_default),
        after => public_view($after, 1),
    };
}

my $input = do { local $/; <STDIN> };
my $response;
eval {
    $response = run(decode_json($input // ''));
    1;
} or do {
    my $error = $@ || 'unknown smtp helper failure';
    $error =~ s/[\r\n]+/ /g;
    emit({ protocol => $PROTOCOL, ok => JSON::PP::false,
           error => { type => 'koha_error', message => $error } });
    exit 1;
};
emit($response);
exit 0;
