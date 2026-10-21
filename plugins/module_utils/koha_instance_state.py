# SPDX-License-Identifier: MIT-0
"""Instance state inspection, ownership marker and per-instance lock for the instance module."""

import contextlib
import grp
import hashlib
import json
import os
import pwd
import tempfile

from ansible_collections.jmz.koha.plugins.module_utils.koha_lock import exclusive_lock


MARKER_SCHEMA = 2
COMPLETE_RESOURCES = ("config", "apache", "site_dir", "user", "group")
# Only options that shape the generated Koha configuration belong in the
# fingerprint. Operation inputs (db_mode, binary and request paths, credentials)
# must not turn an unchanged instance into drift.
FINGERPRINT_KEYS = (
    "marcflavor", "zebralang", "elasticsearch_server", "memcached_servers", "memcached_prefix",
    "memcached_enabled", "enable_sru", "sru_port", "dbhost", "database", "configfile",
    "template_cache_dir", "timezone", "upload_path", "tmp_path", "message_broker", "letsencrypt",
    "tls_termination", "keep_cookies", "vhosts",
)


def fingerprint(p):
    """Hash the non-secret configuration options of a parameter set."""
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if v is not None and k != "password"}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    config = {key: clean(p[key]) for key in FINGERPRINT_KEYS if p.get(key) is not None}
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_marker(path):
    """Return the ownership marker, or {} when it is absent, unreadable or from another schema."""
    try:
        with open(path, "r", encoding="utf-8") as stream:
            marker = json.load(stream)
    except (OSError, ValueError):
        return {}
    if (not isinstance(marker, dict) or marker.get("schema_version") != MARKER_SCHEMA
            or marker.get("state") not in ("present", "requested")):
        return {}
    return marker


def write_marker(path, state, config_fingerprint, request_file=None):
    """Atomically replace the marker with a private (0600) file."""
    content = json.dumps({"schema_version": MARKER_SCHEMA, "state": state, "fingerprint": config_fingerprint,
                          "request_file": request_file}, sort_keys=True) + "\n"
    directory = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(prefix=".ansible-koha-marker-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def remove_marker(path):
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)


def instance_lock(name):
    """Serialize mutations of one instance across concurrent runs."""
    return exclusive_lock("instance", name, "otra ejecución está modificando la instancia %s; reintente cuando termine" % name)


def inspect_state(name, marker_path, request_path):
    """Classify an instance as absent, partial, unmanaged, requested or present.

    ``unmanaged`` is a complete instance without a valid marker: it can be
    adopted without rebuilding it.
    """
    paths = {
        "config": "/etc/koha/sites/%s/koha-conf.xml" % name,
        "apache": "/etc/apache2/sites-available/%s.conf" % name,
        "apache_enabled": "/etc/apache2/sites-enabled/%s.conf" % name,
        "site_dir": "/var/lib/koha/%s" % name,
    }
    found = {key: (os.path.lexists(path) if key == "apache_enabled" else os.path.exists(path)) for key, path in paths.items()}
    for key, function in (("user", pwd.getpwnam), ("group", grp.getgrnam)):
        try:
            function(name + "-koha")
            found[key] = True
        except KeyError:
            found[key] = False
    marker = read_marker(marker_path)
    if not any(found[key] for key in ("config", "apache", "apache_enabled", "user", "group")):
        return "absent", found, marker
    if not all(found[key] for key in COMPLETE_RESOURCES):
        return "partial", found, marker
    if not marker:
        return "unmanaged", found, marker
    if marker["state"] == "requested":
        return ("requested" if os.path.isfile(request_path) else "partial"), found, marker
    return "present", found, marker
