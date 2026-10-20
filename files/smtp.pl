#!/usr/bin/perl
# SPDX-License-Identifier: MIT-0
# Standalone helper that adds a Koha SMTP server and makes it the default.
# It never touches koha-conf.xml or the system default server Koha ships with.
use strict;
use warnings;
use JSON::PP qw(decode_json encode_json);

my $PROTOCOL = 1;
my @FIELDS = qw(host port timeout ssl_mode user_name password debug);
# Set once the transaction commits, so a later failure still reports that Koha was changed.
my $COMMITTED = 0;

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
    my ($state, $is_default, $password_changed) = @_;
    return undef unless $state;
    my %view = %{$state};
    # A password-only change would otherwise leave before and after identical.
    $view{password} = $password_changed ? 'modificada' : length($view{password}) ? JSON::PP::true : JSON::PP::false;
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
    die "Versión de protocolo no soportada\n" unless ref($request) eq 'HASH' && $request->{protocol} == $PROTOCOL;
    die "Operación no soportada\n" unless ($request->{operation} // '') eq 'configure';
    my $desired = $request->{desired};
    die "desired debe ser un objeto\n" unless ref($desired) eq 'HASH';
    die "apply debe ser booleano\n" unless defined $request->{apply} && ($request->{apply} == 0 || $request->{apply} == 1);

    require C4::Context;
    require Koha::Database;
    require Koha::SMTP::Servers;
    require Koha::SMTP::Server;

    my $context = C4::Context->new;
    $context->set_context;
    die "Koha no está inicializado: ejecute initialize antes de smtp\n" if C4::Context->needs_install;

    my $schema = Koha::Database->new->schema;
    die "Esta versión de Koha no puede guardar un servidor SMTP predeterminado (falta smtp_servers.is_default)\n"
        unless $schema->resultset('SmtpServer')->result_source->has_column('is_default');

    my $name = $desired->{name};
    my %wanted = map { $_ => $desired->{$_} } @FIELDS;

    my @matches = Koha::SMTP::Servers->search({ name => $name })->as_list;
    die "Hay más de un servidor SMTP llamado '$name'; renombre los duplicados primero\n" if @matches > 1;
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
        $COMMITTED = 1;
        $server = Koha::SMTP::Servers->find($server->id);
        die "Koha no conservó el servidor SMTP\n" unless $server;
        my $actual = snapshot($server);
        die "Koha no conservó los valores pedidos del servidor SMTP\n" if differs($actual, \%wanted);
        my @now = Koha::SMTP::Servers->search({ is_default => 1 })->as_list;
        die "Koha no dejó '$name' como único servidor SMTP predeterminado\n"
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
        after => public_view($after, 1, $before && "$before->{password}" ne "$wanted{password}"),
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
           committed => $COMMITTED ? JSON::PP::true : JSON::PP::false,
           error => { type => 'koha_error', message => $error } });
    exit 1;
};
emit($response);
exit 0;
