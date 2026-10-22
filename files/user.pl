#!/usr/bin/perl
# SPDX-License-Identifier: MIT-0
# Standalone helper that creates a Koha staff user and sets its permissions.
# It never grants superlibrarian and refuses to demote an existing superlibrarian.
use strict;
use warnings;
use utf8;
use JSON::PP qw(decode_json encode_json);

my $PROTOCOL = 1;
# Set once the transaction commits, so a later failure still reports that Koha was changed.
my $COMMITTED = 0;
my $SECRET = '';

sub emit {
    my ($payload) = @_;
    print STDOUT encode_json($payload), "\n";
}

sub bool { return $_[0] ? JSON::PP::true : JSON::PP::false }

# Flatten Koha's permissions() (or the declared lists) into {module => 1} or {module => [sorted subpermission codes]}.
sub normalize_permissions {
    my ($permissions) = @_;
    my %granted;
    for my $module (keys %{$permissions}) {
        my $value = $permissions->{$module};
        if (ref $value eq 'HASH' || ref $value eq 'ARRAY') {
            my %set = ref $value eq 'HASH' ? %{$value} : map { $_ => 1 } @{$value};
            my @codes = sort grep { $set{$_} } keys %set;
            $granted{$module} = \@codes if @codes;
        } elsif ($value) {
            $granted{$module} = 1;
        }
    }
    return \%granted;
}

# Koha silently ignores unknown flags and subpermissions, so unknown names are rejected here.
sub check_permissions {
    my ($schema, $desired) = @_;
    my %bit = map { $_->flag => $_->bit } $schema->resultset('Userflag')->search->all;
    my %codes;
    push @{ $codes{ $_->get_column("module_bit") } }, $_->code for $schema->resultset('Permission')->search->all;
    for my $module (sort keys %{$desired}) {
        die "Módulo de permisos desconocido: $module\n" unless exists $bit{$module};
        next unless ref $desired->{$module} eq 'ARRAY';
        my %known = map { $_ => 1 } @{ $codes{ $bit{$module} } || [] };
        for my $code (@{ $desired->{$module} }) {
            die "Permiso desconocido en $module: $code\n" unless $known{$code};
        }
    }
}

# Koha's set_permissions format: {module => 1} or {module => {code => 1}}.
sub koha_permissions {
    my ($granted) = @_;
    my %koha;
    for my $module (keys %{$granted}) {
        $koha{$module} = ref $granted->{$module} ? +{ map { $_ => 1 } @{ $granted->{$module} } } : 1;
    }
    return \%koha;
}

sub snapshot {
    my ($patron) = @_;
    return {
        username    => $patron->userid,
        firstname   => $patron->firstname // '',
        surname     => $patron->surname // '',
        cardnumber  => $patron->cardnumber,
        email       => $patron->email,
        library     => $patron->branchcode,
        category    => $patron->categorycode,
        permissions => normalize_permissions($patron->permissions),
    };
}

# The password is never reported, only whether this run changes it.
sub public_view {
    my ($state, $password_state) = @_;
    return undef unless $state;
    return { %{$state}, password => $password_state };
}

sub run {
    my ($request) = @_;
    die "Versión de protocolo no soportada\n" unless ref($request) eq 'HASH' && $request->{protocol} == $PROTOCOL;
    die "Operación no soportada\n" unless ($request->{operation} // '') eq 'configure';
    my $desired = $request->{desired};
    die "desired debe ser un objeto\n" unless ref($desired) eq 'HASH' && ref($desired->{permissions}) eq 'HASH';
    die "apply debe ser booleano\n" unless defined $request->{apply} && ($request->{apply} == 0 || $request->{apply} == 1);
    $SECRET = $desired->{password};

    require C4::Context;
    require C4::Auth;
    require Koha::Database;
    require Koha::AuthUtils;
    require Koha::Email;
    require Koha::Libraries;
    require Koha::Patron;
    require Koha::Patrons;
    require Koha::Patron::Categories;

    my $context = C4::Context->new;
    $context->set_context;
    die "Koha no está inicializado: ejecute initialize antes de user\n" if C4::Context->needs_install;

    my $schema = Koha::Database->new->schema;
    die "Esta versión de Koha no puede administrar permisos (falta Koha::Patron->set_permissions)\n"
        unless Koha::Patron->can('set_permissions');

    my $wanted_permissions = normalize_permissions($desired->{permissions});
    die "superlibrarian no puede concederse con este módulo\n" if $wanted_permissions->{superlibrarian};
    check_permissions($schema, $wanted_permissions);

    die "La biblioteca '$desired->{library}' no existe\n" unless Koha::Libraries->find($desired->{library});
    my $category = Koha::Patron::Categories->find($desired->{category})
        or die "La categoría '$desired->{category}' no existe\n";
    die "El correo no es válido para Koha\n"
        if defined($desired->{email}) && length($desired->{email}) && !Koha::Email->is_valid($desired->{email});
    if (defined $desired->{cardnumber}) {
        require Koha::Policy::Patrons::Cardnumber;
        die "Koha rechazó el número de tarjeta\n" unless Koha::Policy::Patrons::Cardnumber->is_valid($desired->{cardnumber});
    }

    my @matches = Koha::Patrons->search({ userid => $desired->{username} })->as_list;
    my $patron = $matches[0];
    my $before = $patron ? snapshot($patron) : undef;
    if ($patron) {
        die "El usuario '$desired->{username}' es superlibrarian; este módulo no cambia sus privilegios\n"
            if $patron->is_superlibrarian;
    }

    # Profile fields: required ones are always reconciled, optional ones only when declared.
    my %wanted = (
        username => $desired->{username}, surname => $desired->{surname},
        library => $desired->{library}, category => $desired->{category},
        firstname => $desired->{firstname} // ($before ? $before->{firstname} : ''),
        cardnumber => defined $desired->{cardnumber} ? $desired->{cardnumber} : ($before ? $before->{cardnumber} : undef),
        email => defined $desired->{email} ? $desired->{email} : ($before ? $before->{email} : undef),
        permissions => $wanted_permissions,
    );
    my $create = !$patron;
    my $password_wrong = $patron ? !C4::Auth::checkpw_hash($desired->{password}, $patron->password // '!') : 1;
    if ($password_wrong) {
        my ($valid, $error) = Koha::AuthUtils::is_password_valid($desired->{password}, $category);
        die 'Koha rechazó la contraseña para esta categoría (' . ($error || 'inválida') . ")\n" unless $valid;
    }
    my $profile_differs = 0;
    if ($before) {
        for my $field (qw(firstname surname cardnumber email library category)) {
            $profile_differs = 1 if ($before->{$field} // '') ne ($wanted{$field} // '');
        }
    }
    my $permissions_differ = !$before || encode_json_canonical($before->{permissions}) ne encode_json_canonical($wanted_permissions);
    my $changed = $create || $profile_differs || $permissions_differ || $password_wrong;

    if ($request->{apply} && $changed) {
        $schema->txn_do(sub {
            if ($create) {
                $patron = Koha::Patron->new({
                    userid => $wanted{username}, firstname => $wanted{firstname}, surname => $wanted{surname},
                    cardnumber => $wanted{cardnumber}, email => $wanted{email},
                    branchcode => $wanted{library}, categorycode => $wanted{category},
                    privacy => 'default', address => '', city => '', flags => 0,
                });
                $patron->dateexpiry($category->get_expiry_date($patron->dateenrolled));
                $patron->store or die "Koha::Patron->store falló para $wanted{username}\n";
            } elsif ($profile_differs) {
                $patron->set({
                    firstname => $wanted{firstname}, surname => $wanted{surname},
                    cardnumber => $wanted{cardnumber}, email => $wanted{email},
                    branchcode => $wanted{library}, categorycode => $wanted{category},
                })->store or die "Koha::Patron->store falló para $wanted{username}\n";
            }
            $patron->set_password({ password => $desired->{password} }) if $password_wrong;
            $patron->set_permissions(koha_permissions($wanted_permissions)) if $create || $permissions_differ;
        });
        $COMMITTED = 1;
        $patron = Koha::Patrons->find($patron->borrowernumber);
        die "Koha no conservó el usuario\n" unless $patron;
        die "Koha dejó al usuario como superlibrarian\n" if $patron->is_superlibrarian;
        my $actual = snapshot($patron);
        die "Koha no conservó los permisos pedidos\n"
            if encode_json_canonical($actual->{permissions}) ne encode_json_canonical($wanted_permissions);
        die "Koha no conservó la contraseña pedida\n" unless C4::Auth::checkpw_hash($desired->{password}, $patron->password);
    }

    my $after = $request->{apply} && $changed ? snapshot($patron) : { %wanted };
    return {
        protocol => $PROTOCOL, ok => JSON::PP::true,
        changed => bool($changed), created => bool($create),
        updated => bool($before && $profile_differs),
        permissions_changed => bool($before && $permissions_differ),
        password_changed => bool($before && $password_wrong),
        borrowernumber => $patron ? 0 + $patron->borrowernumber : undef,
        before => public_view($before, $before ? JSON::PP::true : JSON::PP::false),
        after => public_view($after, $password_wrong && $before ? 'modificada' : JSON::PP::true),
    };
}

sub encode_json_canonical {
    return JSON::PP->new->canonical->encode($_[0]);
}

my $input = do { local $/; <STDIN> };
my $response;
eval {
    $response = run(decode_json($input // ''));
    1;
} or do {
    my $error = $@ || 'unknown user helper failure';
    $error = ref($error) ? ref($error) . ': ' . ($error->can('error') ? $error->error : '') : $error;
    $error =~ s/\Q$SECRET\E/********/g if length $SECRET;
    $error =~ s/[\r\n]+/ /g;
    $error =~ s/\s+\z//;
    emit({ protocol => $PROTOCOL, ok => JSON::PP::false,
           committed => bool($COMMITTED),
           error => { type => 'koha_error', message => $error } });
    exit 1;
};
emit($response);
exit 0;
