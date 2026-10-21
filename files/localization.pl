#!/usr/bin/perl
# SPDX-License-Identifier: MIT-0
# Standalone helper for instance-scoped Koha localization preferences.
use strict;
use warnings;
use JSON::PP qw(decode_json encode_json);

my $PROTOCOL = 1;
my %SELECTOR_MODES = map { $_ => 1 } qw(top footer both);
my @UPDATED_PREFERENCES;

sub emit {
    my ($payload) = @_;
    print STDOUT encode_json($payload), "\n";
}

sub version_parts {
    my ($raw) = @_;
    die "Koha preference Version is empty or malformed" unless defined $raw && $raw =~ /^(\d{2})\.(\d{2})(?:\.(\d+))?/;
    return [ 0 + $1, 0 + $2, 0 + ($3 || 0) ];
}

sub version_at_least_2411 {
    my ($parts) = @_;
    return $parts->[0] > 24 || ($parts->[0] == 24 && $parts->[1] >= 11);
}

sub preference_row {
    my ($schema, $name) = @_;
    return $schema->resultset('Systempreference')->find({ variable => $name });
}

sub installed_language_codes {
    my ($interface, $theme) = @_;
    my $languages = C4::Languages::getTranslatedLanguages($interface, $theme);
    die "C4::Languages returned an invalid language catalog for $interface"
        unless ref($languages) eq 'ARRAY';
    my %codes;
    for my $language (@{$languages}) {
        next unless ref($language) eq 'HASH';
        for my $candidate ($language, @{ ref($language->{sublanguages_loop}) eq 'ARRAY' ? $language->{sublanguages_loop} : [] }) {
            next unless ref($candidate) eq 'HASH';
            my $code = $candidate->{rfc4646_subtag} // $candidate->{language_code};
            $codes{$code} = 1 if defined $code;
        }
    }
    # English is the Koha source language and does not require a separate translation package.
    $codes{en} = 1;
    return \%codes;
}

sub requested_preferences {
    my ($desired, $staff_pref) = @_;
    my %values;
    if (exists $desired->{staff_languages}) {
        $values{$staff_pref} = join(',', @{$desired->{staff_languages}});
    }
    if (exists $desired->{opac_languages}) {
        $values{OPACLanguages} = join(',', @{$desired->{opac_languages}});
    }
    if (exists $desired->{opac_language_selector}) {
        $values{opaclanguagesdisplay} = $desired->{opac_language_selector} ? '1' : '0';
    }
    if (exists $desired->{opac_selector_position}) {
        $values{OpacLangSelectorMode} = $desired->{opac_selector_position};
    }
    if (exists $desired->{staff_selector_position}) {
        $values{StaffLangSelectorMode} = $desired->{staff_selector_position};
    }
    return \%values;
}

sub run {
    my ($request) = @_;
    die "Unsupported protocol version" unless ref($request) eq 'HASH' && $request->{protocol} == $PROTOCOL;
    die "Unsupported operation" unless ($request->{operation} // '') eq 'configure';
    die "desired configuration must be a non-empty object"
        unless ref($request->{desired}) eq 'HASH' && keys %{$request->{desired}};
    die "apply must be a boolean" unless defined $request->{apply} && ($request->{apply} == 0 || $request->{apply} == 1);

    require C4::Context;
    require Koha::Database;
    require C4::Languages;

    my $context = C4::Context->new;
    $context->set_context;
    my $schema = Koha::Database->new->schema;
    my $version_row = preference_row($schema, 'Version');
    die "Koha is not initialized: the Version system preference is absent" unless $version_row;
    my $version = $version_row->value;
    my $parts = version_parts($version);
    my $new_schema = version_at_least_2411($parts);
    my $new_row = preference_row($schema, 'StaffInterfaceLanguages');
    my $old_row = preference_row($schema, 'language');
    my $staff_pref = $new_schema ? 'StaffInterfaceLanguages' : 'language';
    my $selected_row = $new_schema ? $new_row : $old_row;
    die "Koha version $version requires $staff_pref, but that preference is absent from the initialized schema"
        unless $selected_row;
    die "Koha version $version is incompatible with the installed staff language preference schema"
        if ($new_schema && !$new_row) || (!$new_schema && !$old_row);

    my %current;
    my %current_raw;
    my $values = requested_preferences($request->{desired}, $staff_pref);
    for my $name (sort keys %{$values}) {
        my $row = preference_row($schema, $name);
        die "Required system preference $name is absent from this Koha schema" unless $row;
        my $raw = C4::Context->preference($name);
        die "System preference $name has an undefined value" unless defined $raw;
        my $schema_value = $row->value;
        die "C4::Context could not read system preference $name consistently"
            unless defined $schema_value && "$raw" eq "$schema_value";
        if ($name eq 'OpacLangSelectorMode' || $name eq 'StaffLangSelectorMode') {
            # Koha keeps these choices in its preference (.pref) files and leaves
            # systempreferences.options empty, so they cannot be read from the database.
            die "System preference $name does not accept the requested value '$values->{$name}'"
                unless $SELECTOR_MODES{$values->{$name}};
        }
        $current_raw{$name} = $raw;
        if ($name eq $staff_pref || $name eq 'OPACLanguages') {
            my @list = grep { length } map { s/^\s+|\s+$//gr } split /,/, $raw, -1;
            $current{$name} = \@list;
        } elsif ($name eq 'opaclanguagesdisplay') {
            die "System preference opaclanguagesdisplay has unexpected value '$raw'" unless $raw eq '0' || $raw eq '1';
            $current{$name} = $raw eq '1' ? JSON::PP::true : JSON::PP::false;
        } else {
            $current{$name} = $raw;
        }
    }

    my %interfaces;
    if (exists $request->{desired}->{staff_languages}) {
        my $theme = C4::Context->preference('template') || 'prog';
        $interfaces{staff} = installed_language_codes('intranet', $theme);
    }
    if (exists $request->{desired}->{opac_languages}) {
        my $theme = C4::Context->preference('opacthemes') || 'bootstrap';
        $interfaces{opac} = installed_language_codes('opac', $theme);
    }

    my %before;
    my %after;
    my @updates;
    my @pref_order = ($staff_pref, 'OPACLanguages', 'opaclanguagesdisplay', 'OpacLangSelectorMode', 'StaffLangSelectorMode');
    for my $name (@pref_order) {
        next unless exists $values->{$name};
        my $want = $values->{$name};
        my $is_languages = $name eq $staff_pref || $name eq 'OPACLanguages';
        if ($is_languages) {
            my $interface = $name eq $staff_pref ? 'staff' : 'opac';
            for my $language (@{$request->{desired}->{$name eq $staff_pref ? 'staff_languages' : 'opac_languages'}}) {
                die "Language $language is not installed with usable $interface translation resources; install it first with jmz.koha.translate"
                    unless $interfaces{$interface}->{$language};
            }
            $want = join(',', @{$request->{desired}->{$name eq $staff_pref ? 'staff_languages' : 'opac_languages'}});
            $before{$name eq $staff_pref ? 'staff_languages' : 'opac_languages'} = $current{$name};
            $after{$name eq $staff_pref ? 'staff_languages' : 'opac_languages'} = $request->{desired}->{$name eq $staff_pref ? 'staff_languages' : 'opac_languages'};
        } elsif ($name eq 'opaclanguagesdisplay') {
            $want = $request->{desired}->{opac_language_selector} ? '1' : '0';
            $before{opac_language_selector} = $current{$name};
            $after{opac_language_selector} = $request->{desired}->{opac_language_selector} ? JSON::PP::true : JSON::PP::false;
        } elsif ($name eq 'OpacLangSelectorMode') {
            $before{opac_selector_position} = $current{$name};
            $after{opac_selector_position} = $want;
        } else {
            $before{staff_selector_position} = $current{$name};
            $after{staff_selector_position} = $want;
        }
        my $compare_current = $is_languages ? join(',', @{$current{$name}}) : $current_raw{$name};
        push @updates, $name if $compare_current ne $want;
    }

    @UPDATED_PREFERENCES = ();
    if ($request->{apply}) {
        # All-or-nothing: preferences are written and read back inside one transaction, so a
        # failure never leaves some of them changed and others not.
        $schema->txn_begin;
        my $ok = eval {
            for my $name (@updates) {
                C4::Context->set_preference($name, $values->{$name});
            }
            # Read back every managed value through Koha's API; report observed state, not the plan.
            for my $name (@pref_order) {
                next unless exists $values->{$name};
                my $actual = C4::Context->preference($name);
                die "Koha did not retain the requested value for $name" unless defined $actual && $actual eq $values->{$name};
                if ($name eq $staff_pref || $name eq 'OPACLanguages') {
                    my @languages = grep { length } map { s/^\s+|\s+$//gr } split /,/, $actual, -1;
                    $after{$name eq $staff_pref ? 'staff_languages' : 'opac_languages'} = \@languages;
                } elsif ($name eq 'opaclanguagesdisplay') {
                    die "Koha returned an invalid selector value for opaclanguagesdisplay" unless $actual eq '0' || $actual eq '1';
                    $after{opac_language_selector} = $actual eq '1' ? JSON::PP::true : JSON::PP::false;
                } elsif ($name eq 'OpacLangSelectorMode') {
                    $after{opac_selector_position} = $actual;
                } else {
                    $after{staff_selector_position} = $actual;
                }
            }
            $schema->txn_commit;
            1;
        };
        my $error = $@;
        $schema->txn_rollback unless $ok;
        # Values cached while the transaction was open may be stale either way.
        C4::Context->clear_syspref_cache;
        die "Preference update failed and was rolled back; no preference was changed: " . ($error || 'unknown Koha preference update error')
            unless $ok;
        @UPDATED_PREFERENCES = @updates;
    }

    return {
        protocol => $PROTOCOL, ok => JSON::PP::true, koha_version => "$version",
        staff_preference => $staff_pref, before => \%before, after => \%after,
        updated_preferences => $request->{apply} ? \@UPDATED_PREFERENCES : \@updates,
    };
}

my $input = do { local $/; <STDIN> };
my $request;
my $response;
eval {
    $request = decode_json($input // '');
    $response = run($request);
    1;
} or do {
    my $error = $@ || 'unknown localization helper failure';
    $error =~ s/[\r\n]+/ /g;
    emit({ protocol => $PROTOCOL, ok => JSON::PP::false,
           error => { type => 'koha_error', message => $error },
           details => { updated_preferences => \@UPDATED_PREFERENCES,
                        partial => @UPDATED_PREFERENCES ? JSON::PP::true : JSON::PP::false } });
    exit 1;
};
emit($response);
exit 0;
