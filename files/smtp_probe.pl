#!/usr/bin/perl
# SPDX-License-Identifier: MIT-0
# Read-only Koha capability, initialization and SMTP precedence probe.
use strict;
use warnings;

my ($needs_install, $database_default, $source);
eval {
    require C4::Context;
    C4::Context->import();
    $needs_install = C4::Context->needs_install ? 1 : 0;
    if (!$needs_install) {
        require Koha::SMTP::Servers;
        my $servers = Koha::SMTP::Servers->new;
        my $default = $servers->get_default;
        die "No default SMTP server object" unless $default;
        my $configured = C4::Context->config('smtp_server');
        $database_default = $default->can('is_system_default') && !$default->is_system_default ? 1 : 0;
        $source = $database_default ? 'database' : ($configured ? 'xml' : 'koha_default');
    }
    1;
} or do {
    print "error\n";
    exit 0;
};
print join("\t", 'ok', $needs_install, defined($database_default) ? $database_default : '-',
           defined($source) ? $source : 'uninitialized'), "\n";
