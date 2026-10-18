#!/usr/bin/perl
# SPDX-License-Identifier: MIT-0
# Versioned helper protocol for the jmz.koha.initialize action plugin.
use strict;
use warnings;
use JSON::PP qw(decode_json encode_json);
use File::Basename qw(basename);
use Cwd qw(abs_path);
use C4::Context;
use C4::Installer;
use C4::Languages qw(getAllLanguages getTranslatedLanguages);
use Koha;
use Koha::Database;
use Koha::Library;
use Koha::Libraries;
use Koha::Patron;
use Koha::Patron::Category;
use Koha::Patron::Categories;
use Koha::Patrons;
use Koha::ItemType;
use Koha::ItemTypes;
use Koha::CirculationRules;
use Koha::AuthUtils;
use Koha::Policy::Patrons::Cardnumber;

our $PROTOCOL = 1;
our @APPLIED_ACTIONS;
our @WARNINGS;
our $INITIAL_STATE;
our $OBSERVED_STATE;
our $CHANGED = 0;
our $PHASE = 'state_detection';
open our $RESULT, '>&', \*STDOUT or die "cannot preserve result stream";
open STDOUT, '>&', \*STDERR or die "cannot redirect diagnostic stream";

sub fail {
    my ($kind, $message, $extra) = @_;
    my $result = { protocol => $PROTOCOL, ok => JSON::PP::false, error => { type => $kind, message => $message } };
    $result->{error}{details} = $extra if defined $extra;
    print {$RESULT} encode_json($result);
    exit 2;
}

sub emit {
    my ($value) = @_;
    print {$RESULT} encode_json($value);
    exit 0;
}

sub record_action {
    my ($actions, $changed_ref, $action) = @_;
    push @$actions, $action;
    push @APPLIED_ACTIONS, $action;
    $$changed_ref = 1;
    $CHANGED = 1;
}

sub safe_text {
    my ($text, $secret) = @_;
    $text = defined($text) ? "$text" : 'unknown error';
    $text =~ s/\Q$secret\E/[redacted]/g if defined($secret) && length($secret);
    $text =~ s/[\r\n]+/ /g;
    return substr($text, 0, 1000);
}

sub flatten_catalog {
    my ($catalog) = @_;
    my @files;
    for my $section (@{$catalog || []}) {
        next unless ref($section) eq 'HASH' && ref($section->{frameworks}) eq 'ARRAY';
        for my $entry (@{$section->{frameworks}}) {
            next unless ref($entry) eq 'HASH' && defined $entry->{fwkfile};
            push @files, $entry;
        }
    }
    return @files;
}

sub verified_catalog_file {
    my ($entry, $root) = @_;
    my $path = $entry->{fwkfile};
    my $real = abs_path($path);
    my $realroot = abs_path($root);
    die "Koha installer data directory is unavailable" unless defined($realroot) && -d $realroot;
    die "Koha catalog path is not a regular non-symlink file" unless defined($real) && -f $real && $path eq $real;
    die "Koha catalog path escaped the installer data directory" unless index($real, "$realroot/") == 0;
    return $real;
}

sub detect_state {
    my ($installer) = @_;
    my $dbh = C4::Context->dbh;
    my $database = C4::Context->config('database');
    my $table_rows = eval {
        $dbh->selectcol_arrayref(
            'SELECT table_name FROM information_schema.tables WHERE table_schema = ?',
            undef, $database
        );
    };
    return ('inconsistent', { reason => 'Unable to inspect the selected database schema' }) unless $table_rows;
    my @tables = @$table_rows;
    return ('uninitialized', { tables => 0, needs_install => 1 }) unless @tables;
    my %actual_tables = map { lc($_) => 1 } @tables;
    my @expected_sources = eval { Koha::Database->schema->sources };
    return ('inconsistent', { tables => scalar(@tables), reason => 'Koha schema metadata is unavailable' }) if $@ || !@expected_sources;
    my @missing_tables = grep {
        my $source = eval { Koha::Database->schema->source($_)->name };
        !$source || !$actual_tables{lc($source)};
    } @expected_sources;
    return ('inconsistent', { tables => scalar(@tables), missing_tables => [ @missing_tables[0 .. ($#missing_tables < 9 ? $#missing_tables : 9)] ] })
        if @missing_tables;
    my $schema_ok = eval {
        $dbh->selectrow_array('SELECT 1 FROM systempreferences WHERE variable = ?', undef, 'Version');
        1;
    };
    return ('inconsistent', { tables => scalar(@tables), reason => 'systempreferences is unavailable' }) unless $schema_ok;
    my $version = C4::Context->preference('Version');
    my $needs_install = C4::Context->needs_install ? 1 : 0;
    my $frameworks = C4::Context->preference('FrameworksLoaded') || '';
    return ('schema_created', { tables => scalar(@tables), needs_install => 1 })
        unless C4::Context->preference('marcflavour') || $frameworks;
    return ('data_incomplete', { tables => scalar(@tables), needs_install => $needs_install, frameworks_loaded => $frameworks })
        if $needs_install || !$version || !C4::Context->preference('marcflavour') || !$frameworks;
    my $software_version = Koha::version();
    my $normalized_version = $software_version;
    $normalized_version =~ s/(.*\..*)\.(.*)\.(.*)/$1$2$3/;
    return ('upgrade_required', { database_version => "$version", software_version => "$software_version" })
        if "$version" ne "$normalized_version";
    my $libraries = Koha::Libraries->search->count;
    my $staff_categories = Koha::Patron::Categories->search({ category_type => 'S' })->count;
    my $item_types = Koha::ItemTypes->search->count;
    my $superlibrarians = 0;
    for my $patron (Koha::Patrons->search->as_list) {
        $superlibrarians++ if $patron->is_superlibrarian;
    }
    my $rules = Koha::CirculationRules->search->count;
    my $details = { tables => scalar(@tables), version => "$version", libraries => $libraries,
        staff_categories => $staff_categories, superlibrarians => $superlibrarians,
        item_types => $item_types, circulation_rules => $rules };
    return ('initialized', $details)
        if $libraries && $staff_categories && $superlibrarians && $item_types && $rules;
    return ('onboarding_required', $details);
}

sub assert_db_privileges {
    my ($write_schema) = @_;
    my $dbh = C4::Context->dbh;
    my $grants = eval { $dbh->selectcol_arrayref('SHOW GRANTS') };
    die 'Unable to verify database grants for the configured Koha instance' unless $grants && @$grants;
    my $database = C4::Context->config('database');
    die 'The selected Koha instance does not define a database name' unless defined($database) && length($database);
    my $quoted_database = quotemeta($database);
    my @instance_grants = grep {
        /\bON\s+(?:`?$quoted_database`?\.(?:\*|`?[^\s`]+`?)|\*\.\*)/i
    } @$grants;
    die 'No database grants apply to the configured Koha database' unless @instance_grants;
    my $grant_text = lc(join ' ', @instance_grants);
    return if $grant_text =~ /all privileges/;
    my @required = $write_schema ? qw(select insert update delete create alter index references)
                                  : qw(select insert update delete);
    my @missing = grep { $grant_text !~ /\b\Q$_\E\b/ } @required;
    die 'Database user lacks required grants (' . join(',', @missing) . ')' if @missing;
}

sub assert_instance_database {
    my $database = C4::Context->config('database');
    my $test_database = C4::Context->config('database_test');
    die 'The selected instance has no configured database name' unless defined($database) && length($database);
    die 'Refusing to initialize a test database configured as database_test'
        if defined($test_database) && length($test_database);
}

sub assert_capabilities {
    my ($installer) = @_;
    my @required = (
        [undef, $installer, 'load_db_schema'], [undef, $installer, 'sample_data_sql_list'],
        [undef, $installer, 'marc_framework_sql_list'], [undef, $installer, 'load_sql_in_order'],
        [undef, $installer, 'set_marcflavour_syspref'], [undef, $installer, 'set_languages_syspref'],
        [undef, $installer, 'set_version_syspref'], ['Koha::Library', undef, 'store'],
        ['Koha::Patron::Category', undef, 'store'], ['Koha::Patron', undef, 'set_password'],
        ['Koha::ItemType', undef, 'store'], ['Koha::CirculationRules', undef, 'set_rules'],
        ['Koha::CirculationRules', undef, 'get_effective_rule'],
    );
    my @missing = map { $_->[2] } grep {
        my ($class, $object, $method) = @$_;
        $object ? !$object->can($method) : !$class->can($method);
    } @required;
    die 'Installed Koha lacks required API capability: ' . join(', ', @missing) if @missing;
}

sub assert_existing_install_preferences {
    my ($request, $state) = @_;
    return unless $state eq 'onboarding_required' || $state eq 'initialized';
    my $flavour = C4::Context->preference('marcflavour') || '';
    die "Existing Koha MARC flavour ($flavour) conflicts with requested flavour ($request->{marc_flavour})"
        if $flavour ne $request->{marc_flavour};
    return if $request->{language} eq 'en';
    my $staff = C4::Context->preference('StaffInterfaceLanguages') || '';
    my $opac = C4::Context->preference('OPACLanguages') || '';
    my %staff_languages = map { $_ => 1 } split /\s*,\s*/, $staff;
    my %opac_languages = map { $_ => 1 } split /\s*,\s*/, $opac;
    die "Existing Koha language preferences conflict with requested language ($request->{language})"
        unless $staff_languages{$request->{language}} && $opac_languages{$request->{language}};
}

sub api_probe {
    my ($request) = @_;
    assert_instance_database();
    my $installer = C4::Installer->new() or die 'C4::Installer could not connect to the instance database';
    my ($state, $state_info) = detect_state($installer);
    my $caps = {
        load_db_schema => $installer->can('load_db_schema') ? 1 : 0,
        sample_data_sql_list => $installer->can('sample_data_sql_list') ? 1 : 0,
        marc_framework_sql_list => $installer->can('marc_framework_sql_list') ? 1 : 0,
        load_sql_in_order => $installer->can('load_sql_in_order') ? 1 : 0,
    };
    my $result = {
        protocol => $PROTOCOL,
        ok => JSON::PP::true,
        operation => 'inspect',
        state => $state,
        state_info => $state_info,
        koha_version => scalar(Koha::version()),
        capabilities => $caps,
        onboarding => $state_info,
    };
    return $result;
}

sub ensure_library {
    my ($data, $changed, $actions) = @_;
    my $code = $data->{code};
    my $existing = Koha::Libraries->find($code);
    if ($existing) {
        die "Existing library $code has a different name" if ($existing->branchname // '') ne $data->{name};
        return;
    }
    Koha::Library->new({ branchcode => $code, branchname => $data->{name} })->store
        or die "Koha::Library->store failed for $code";
    record_action($actions, $changed, "library_created:$code");
}

sub ensure_category {
    my ($data, $changed, $actions) = @_;
    my $code = $data->{code};
    my $existing = Koha::Patron::Categories->find($code);
    if ($existing) {
        die "Existing patron category $code has different declared attributes" if
            ($existing->description // '') ne $data->{description} ||
            ($existing->category_type // '') ne $data->{type} ||
            ($existing->enrolmentperiod // 0) != $data->{enrolment_period} ||
            ($existing->default_privacy // '') ne $data->{default_privacy};
        return;
    }
    my $fields = {
        categorycode => $code,
        description => $data->{description},
        category_type => $data->{type},
        enrolmentperiod => $data->{enrolment_period},
        overduenoticerequired => 0,
        default_privacy => $data->{default_privacy},
    };
    Koha::Patron::Category->new($fields)->store or die "Koha::Patron::Category->store failed for $code";
    record_action($actions, $changed, "patron_category_created:$code");
}

sub ensure_admin {
    my ($data, $password, $changed, $actions) = @_;
    my $existing = Koha::Patrons->search({ userid => $data->{username} })->single;
    if ($existing) {
        for my $pair ([firstname => 'firstname'], [surname => 'surname'], [cardnumber => 'cardnumber'],
                      [branchcode => 'library'], [categorycode => 'category']) {
            my ($field, $key) = @$pair;
            die "Existing administrator identity conflicts at $field" if ($existing->$field // '') ne $data->{$key};
        }
        die 'Existing administrator does not have effective superlibrarian privileges'
            unless $existing->is_superlibrarian;
        return;
    }
    my $category = Koha::Patron::Categories->find($data->{category});
    die 'Administrator category must be a staff category (type S)' unless $category && $category->category_type eq 'S';
    die 'Koha rejected the administrator card number' unless Koha::Policy::Patrons::Cardnumber->is_valid($data->{cardnumber});
    my ($password_valid, $password_error) = Koha::AuthUtils::is_password_valid($password, $category);
    die 'Koha rejected the administrator password for this category (' . ($password_error || 'invalid') . ')'
        unless $password_valid;
    my $schema = Koha::Database->schema;
    my $txn = $schema->txn_scope_guard;
    my $patron_data = {
        userid => $data->{username}, firstname => $data->{firstname}, surname => $data->{surname},
        cardnumber => $data->{cardnumber}, branchcode => $data->{library}, categorycode => $data->{category},
        privacy => 'default', address => '', city => '', flags => 1,
    };
    $patron_data->{dateexpiry} = $category->get_expiry_date($patron_data->{dateenrolled});
    my $patron = Koha::Patron->new($patron_data)->store or die 'Koha::Patron->store failed for administrator';
    $patron->set_password({ password => $password });
    die 'Koha did not persist administrator superlibrarian privileges' unless $patron->is_superlibrarian;
    $txn->commit;
    record_action($actions, $changed, 'administrator_created');
}

sub ensure_item_type {
    my ($data, $changed, $actions) = @_;
    my $code = $data->{code};
    my $existing = Koha::ItemTypes->find($code);
    if ($existing) {
        die "Existing item type $code has a different description" if ($existing->description // '') ne $data->{description};
        return;
    }
    Koha::ItemType->new({ itemtype => $code, description => $data->{description} })->store
        or die "Koha::ItemType->store failed for $code";
    record_action($actions, $changed, "item_type_created:$code");
}

sub ensure_rules {
    my ($entries, $changed, $actions) = @_;
    for my $entry (@$entries) {
        my $rules = $entry->{rules};
        my @missing;
        for my $name (sort keys %$rules) {
            my $current = Koha::CirculationRules->get_effective_rule({
                rule_name => $name, categorycode => $entry->{category},
                itemtype => $entry->{item_type}, branchcode => $entry->{library},
            });
            if ($current && defined($current->rule_value) && $current->rule_value eq "$rules->{$name}") {
                next;
            }
            if ($current && ($current->branchcode // '') eq $entry->{library}
                && ($current->categorycode // '') eq $entry->{category}
                && ($current->itemtype // '') eq $entry->{item_type}) {
                die "Exact circulation rule $name already differs; automatic overwrite is disabled";
            }
            push @missing, $name;
        }
        next unless @missing;
        my %subset = map { $_ => $rules->{$_} } @missing;
        Koha::CirculationRules->set_rules({
            branchcode => $entry->{library}, categorycode => $entry->{category},
            itemtype => $entry->{item_type}, rules => \%subset,
        });
        for my $name (@missing) {
            my $value = Koha::CirculationRules->get_effective_rule_value({
                rule_name => $name, categorycode => $entry->{category},
                itemtype => $entry->{item_type}, branchcode => $entry->{library},
            });
            die "Circulation rule $name failed postcondition" unless defined($value) && "$value" eq "$rules->{$name}";
        }
        record_action($actions, $changed, "circulation_rules_set:$entry->{library}:$entry->{category}:$entry->{item_type}");
    }
}

sub initialize_install {
    my ($request) = @_;
    $PHASE = 'database_detection';
    assert_instance_database();
    my $installer = C4::Installer->new() or die 'C4::Installer could not connect to the instance database';
    assert_capabilities($installer);
    my ($before, $info) = detect_state($installer);
    $INITIAL_STATE = $before unless defined $INITIAL_STATE;
    $OBSERVED_STATE = $before;
    die "Unsafe installation state: $before" if $before eq 'data_incomplete' || $before eq 'inconsistent' || $before eq 'upgrade_required';
    assert_existing_install_preferences($request, $before);
    assert_db_privileges($before eq 'uninitialized');
    my @actions;
    my $changed = 0;
    if ($before eq 'uninitialized') {
        $PHASE = 'schema_creation';
        my $schema_error = $installer->load_db_schema();
        die "load_db_schema reported errors: " . safe_text($schema_error) if defined($schema_error) && length($schema_error);
        my ($after_schema) = detect_state($installer);
        die 'Schema postcondition failed after load_db_schema' unless $after_schema eq 'schema_created';
        record_action(\@actions, \$changed, 'schema_created');
        $before = 'schema_created';
        $OBSERVED_STATE = $before;
    }
    if ($before eq 'schema_created') {
        $PHASE = 'initial_data';
        my $flavour = $request->{marc_flavour};
        my $lang = $request->{language};
        my $languages = getAllLanguages();
        my %language_codes = map { ($_->{language_code} => 1) } @$languages;
        die "Language $lang is not in Koha's installed language catalog" unless $language_codes{$lang};
        my ($fallback, $framework_catalog) = $installer->marc_framework_sql_list($lang, $flavour);
        my ($sample_fallback, $sample_catalog) = $installer->sample_data_sql_list($lang);
        push @WARNINGS, 'Koha no dispone de datos de instalación traducidos para el idioma solicitado; se usaron archivos en inglés'
            if $fallback || $sample_fallback;
        my $dbms = C4::Context->config('db_scheme') || 'mysql';
        my $data_root = C4::Context->config('intranetdir') . "/installer/data/$dbms";
        my @load;
        for my $entry (flatten_catalog($framework_catalog)) {
            push @load, verified_catalog_file($entry, $data_root) if $entry->{mandatory};
        }
        for my $entry (flatten_catalog($sample_catalog)) {
            push @load, verified_catalog_file($entry, $data_root) if $entry->{mandatory};
        }
        my %optional = map { $_ => 1 } @{ $request->{sample_data} || [] };
        for my $section (@{$sample_catalog || []}) {
            next unless ref($section) eq 'HASH';
            for my $entry (@{$section->{frameworks} || []}) {
                next if $entry->{mandatory};
                my $id = ($section->{code} // '') . '/' . basename($entry->{fwkfile});
                next unless delete $optional{$id};
                push @load, verified_catalog_file($entry, $data_root);
            }
        }
        die 'Unknown optional sample_data identifier(s)' if keys %optional;
        die 'Koha did not provide mandatory MARC or sample data files' unless @load;
        $installer->set_marcflavour_syspref($flavour);
        require C4::Languages;
        my ($fwk_language, $errors) = $installer->load_sql_in_order($lang, $languages, @load);
        my @failed = map { @{$_->{fwklist} || []} ? grep { defined($_->{error}) && length($_->{error}) } @{$_->{fwklist}} : () } @$errors;
        die 'load_sql_in_order reported failed files: ' . join(', ', map { $_->{fwkname} } @failed) if @failed;
        $installer->set_languages_syspref($lang);
        $PHASE = 'installer_finalize';
        $installer->set_version_syspref();
        my ($after_data) = detect_state($installer);
        die "Installer postcondition failed; observed state $after_data" unless $after_data eq 'onboarding_required';
        record_action(\@actions, \$changed, 'initial_data_loaded');
        record_action(\@actions, \$changed, 'installer_version_registered');
        $OBSERVED_STATE = $after_data;
    }
    return { changed => $changed, previous_state => $before, current_state => 'onboarding_required', actions => \@actions };
}

sub onboard {
    my ($request) = @_;
    $PHASE = 'onboarding';
    my @actions;
    my $changed = 0;
    my $schema = Koha::Database->schema;
    assert_db_privileges(0);
    my $txn = $schema->txn_scope_guard;
    my $action_count = scalar @APPLIED_ACTIONS;
    my $ok = eval {
        ensure_library($request->{library}, \$changed, \@actions);
        for my $category (@{$request->{patron_categories}}) { ensure_category($category, \$changed, \@actions); }
        for my $itemtype (@{$request->{item_types}}) { ensure_item_type($itemtype, \$changed, \@actions); }
        ensure_admin($request->{administrator}, $request->{administrator}{password}, \$changed, \@actions);
        ensure_rules($request->{circulation_rules}, \$changed, \@actions);
        $txn->commit;
        1;
    };
    unless ($ok) {
        my $failure = $@;
        splice @APPLIED_ACTIONS, $action_count;
        $CHANGED = @APPLIED_ACTIONS ? 1 : 0;
        die $failure;
    }
    return { changed => $changed, actions => \@actions };
}

my $raw = do { local $/; <STDIN> };
my $request = eval { decode_json($raw || '') };
fail('protocol_error', 'Invalid JSON request') if $@ || ref($request) ne 'HASH';
fail('protocol_error', 'Unsupported protocol version') unless ($request->{protocol} || 0) == $PROTOCOL;
my $operation = $request->{operation} || '';
my $response;
my $ok = eval {
    if ($operation eq 'inspect') {
        $response = api_probe($request);
    } elsif ($operation eq 'initialize') {
        my $install = initialize_install($request);
        my $business = onboard($request);
        $PHASE = 'final_validation';
        my ($state, $details) = detect_state(C4::Installer->new());
        $OBSERVED_STATE = $state;
        $response = { protocol => $PROTOCOL, ok => JSON::PP::true, operation => 'initialize',
            changed => ($install->{changed} || $business->{changed}) ? JSON::PP::true : JSON::PP::false,
            previous_state => $INITIAL_STATE, current_state => $state,
            actions => [ @{$install->{actions}}, @{$business->{actions}} ], state_info => $details,
            warnings => \@WARNINGS,
            validation => { schema => $state ne 'uninitialized' && $state ne 'inconsistent', onboarding => 1 } };
        die 'final state did not reach initialized' if $state ne 'initialized';
    } else {
        fail('protocol_error', 'Unknown operation');
    }
    1;
};
unless ($ok) {
    my $error = safe_text($@, $request->{administrator}{password});
    my ($detected, $detected_info) = eval { detect_state(C4::Installer->new()) };
    $OBSERVED_STATE = $detected if defined $detected;
    $CHANGED = 1 if @APPLIED_ACTIONS || (defined($INITIAL_STATE) && defined($OBSERVED_STATE) && $INITIAL_STATE ne $OBSERVED_STATE);
    fail('koha_operation_failed', $error, {
        operation => $operation,
        phase => $PHASE,
        previous_state => $INITIAL_STATE,
        current_state => $OBSERVED_STATE,
        state_info => $detected_info,
        changed => $CHANGED ? JSON::PP::true : JSON::PP::false,
        actions => \@APPLIED_ACTIONS,
        warnings => \@WARNINGS,
        partial => $CHANGED ? JSON::PP::true : JSON::PP::false,
    });
}
emit($response);
