#!/usr/bin/perl
# SPDX-License-Identifier: MIT-0
# Standalone helper that restores a Koha superlibrarian account to its declared state
# and reports any other superlibrarian. It never creates or promotes a second one.
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

sub snapshot {
    my ($patron) = @_;
    return {
        username       => $patron->userid,
        firstname      => $patron->firstname // '',
        surname        => $patron->surname // '',
        cardnumber     => $patron->cardnumber,
        email          => $patron->email,
        library        => $patron->branchcode,
        category       => $patron->categorycode,
        superlibrarian => bool($patron->is_superlibrarian),
        expired        => bool($patron->is_expired),
        locked         => bool($patron->account_locked),
        restrictions   => 0 + $patron->restrictions->count,
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
    die "desired debe ser un objeto\n" unless ref($desired) eq 'HASH' && ref($desired->{allowed}) eq 'ARRAY';
    die "unexpected debe ser warn o lock\n" unless ($desired->{unexpected} // '') =~ /\A(?:warn|lock)\z/;
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
    require Koha::Patron::Debarments;
    require Koha::DateUtils;

    my $context = C4::Context->new;
    $context->set_context;
    die "Koha no está inicializado: ejecute initialize antes de superlibrarian\n" if C4::Context->needs_install;

    my $schema = Koha::Database->new->schema;
    die "La biblioteca '$desired->{library}' no existe\n" unless Koha::Libraries->find($desired->{library});
    my $category = Koha::Patron::Categories->find($desired->{category})
        or die "La categoría '$desired->{category}' no existe\n";
    die "La categoría del superlibrarian debe ser de personal (tipo S)\n" unless $category->category_type eq 'S';
    die "El correo no es válido para Koha\n"
        if defined($desired->{email}) && !Koha::Email->is_valid($desired->{email});

    my $patron = Koha::Patrons->search({ userid => $desired->{username} })->single;
    my $before = $patron ? snapshot($patron) : undef;

    # The card number's own account would fail the uniqueness check, so only a new or changed one is validated.
    if (defined $desired->{cardnumber} && (!$before || ($before->{cardnumber} // '') ne $desired->{cardnumber})) {
        require Koha::Policy::Patrons::Cardnumber;
        die "Koha rechazó el número de tarjeta\n" unless Koha::Policy::Patrons::Cardnumber->is_valid($desired->{cardnumber});
    }

    my %wanted = (
        username => $desired->{username}, surname => $desired->{surname},
        library => $desired->{library}, category => $desired->{category},
        firstname => $desired->{firstname} // ($before ? $before->{firstname} : ''),
        cardnumber => defined $desired->{cardnumber} ? $desired->{cardnumber} : ($before ? $before->{cardnumber} : undef),
        email => defined $desired->{email} ? $desired->{email} : ($before ? $before->{email} : undef),
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
    my $not_super = $before && !$before->{superlibrarian};
    my $expired = $before && $before->{expired};
    my $locked = $before && $before->{locked};
    my $restricted = $before && $before->{restrictions} > 0;
    my $new_expiry;
    $new_expiry = $category->get_expiry_date(Koha::DateUtils::dt_from_string()) if $expired;
    die "La categoría no permite calcular un nuevo vencimiento (sin período de inscripción)\n" if $expired && !$new_expiry;
    my $changed = $create || $profile_differs || $password_wrong || $not_super || $expired || $locked || $restricted;

    # Other superlibrarians are always reported. With unexpected=lock they are also locked (never demoted
    # or deleted), and declared ones that an earlier run locked are unlocked; nothing else is unlocked.
    my $dbh = $schema->storage->dbh;
    my %allowed = map { $_ => 1 } @{ $desired->{allowed} };
    my @supers = grep { $_ ne $desired->{username} }
        @{ $dbh->selectcol_arrayref('SELECT userid FROM borrowers WHERE (flags & 1) = 1 AND userid IS NOT NULL') };
    my @unexpected = sort grep { !$allowed{$_} } @supers;
    my @to_lock;
    my @to_restore;
    if ($desired->{unexpected} eq 'lock') {
        @to_lock = grep { !Koha::Patrons->search({ userid => $_ })->single->account_locked } @unexpected;
        @to_restore = sort grep { $allowed{$_} && Koha::Patrons->search({ userid => $_ })->single->account_locked } @supers;
    }
    $changed ||= @to_lock || @to_restore;

    if ($request->{apply} && $changed) {
        $schema->txn_do(sub {
            if ($create) {
                $patron = Koha::Patron->new({
                    userid => $wanted{username}, firstname => $wanted{firstname}, surname => $wanted{surname},
                    cardnumber => $wanted{cardnumber}, email => $wanted{email},
                    branchcode => $wanted{library}, categorycode => $wanted{category},
                    privacy => 'default', address => '', city => '', flags => 1,
                });
                $patron->dateexpiry($category->get_expiry_date($patron->dateenrolled));
                $patron->store or die "Koha::Patron->store falló para $wanted{username}\n";
            } else {
                my %set;
                if ($profile_differs) {
                    %set = (firstname => $wanted{firstname}, surname => $wanted{surname},
                            cardnumber => $wanted{cardnumber}, email => $wanted{email},
                            branchcode => $wanted{library}, categorycode => $wanted{category});
                }
                $set{dateexpiry} = $new_expiry if $expired;
                $set{login_attempts} = 0 if $locked;
                $patron->set(\%set)->store or die "Koha::Patron->store falló para $wanted{username}\n" if %set;
                # Replaces the flags with superlibrarian alone, as initialize creates the account.
                $patron->set_permissions({ superlibrarian => 1 }) if $not_super;
                if ($restricted) {
                    Koha::Patron::Debarments::DelDebarment($_->borrower_debarment_id) for $patron->restrictions->as_list;
                }
            }
            $patron->set_password({ password => $desired->{password} }) if $password_wrong;
            Koha::Patrons->search({ userid => $_ })->single->lock for @to_lock;
            Koha::Patrons->search({ userid => $_ })->single->set({ login_attempts => 0 })->store for @to_restore;
        });
        $COMMITTED = 1;
        $patron = Koha::Patrons->find($patron->borrowernumber);
        die "Koha no conservó el usuario\n" unless $patron;
        my $actual = snapshot($patron);
        die "Koha no dejó al usuario como superlibrarian\n" unless $actual->{superlibrarian};
        die "Koha no dejó la cuenta vigente, desbloqueada y sin restricciones\n"
            if $actual->{expired} || $actual->{locked} || $actual->{restrictions};
        for my $field (qw(firstname surname cardnumber email library category)) {
            die "Koha no conservó $field\n" if ($actual->{$field} // '') ne ($wanted{$field} // '');
        }
        die "Koha no conservó la contraseña pedida\n" unless C4::Auth::checkpw_hash($desired->{password}, $patron->password);
        for my $userid (@to_lock) {
            die "Koha no bloqueó a $userid\n" unless Koha::Patrons->search({ userid => $userid })->single->account_locked;
        }
        for my $userid (@to_restore) {
            die "Koha no desbloqueó a $userid\n" if Koha::Patrons->search({ userid => $userid })->single->account_locked;
        }
    }

    my $projected = { %wanted, superlibrarian => JSON::PP::true, expired => JSON::PP::false,
                      locked => JSON::PP::false, restrictions => 0 };
    my $after = $request->{apply} && $changed ? snapshot($patron) : $projected;
    return {
        protocol => $PROTOCOL, ok => JSON::PP::true,
        changed => bool($changed), created => bool($create),
        updated => bool($before && $profile_differs),
        superlibrarian_restored => bool($not_super),
        password_changed => bool($before && $password_wrong),
        expiry_renewed => bool($expired),
        unlocked => bool($locked),
        restrictions_removed => bool($restricted),
        unexpected_superlibrarians => \@unexpected,
        locked_superlibrarians => \@to_lock,
        restored_superlibrarians => \@to_restore,
        borrowernumber => $patron ? 0 + $patron->borrowernumber : undef,
        before => public_view($before, $before ? JSON::PP::true : JSON::PP::false),
        after => public_view($after, $password_wrong && $before ? 'modificada' : JSON::PP::true),
    };
}

my $input = do { local $/; <STDIN> };
my $response;
eval {
    $response = run(decode_json($input // ''));
    1;
} or do {
    my $error = $@ || 'unknown superlibrarian helper failure';
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
