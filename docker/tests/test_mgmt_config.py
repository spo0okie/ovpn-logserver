#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for OpenVPN Management Interface configuration.

Checks invariants:
- O4.1: server.conf has management directive
- O4.2: management directive is at the beginning of the file
- O4.3: entrypoint.sh creates socket directory
- O4.4: docker-compose.yml mounts management socket
"""

import os
import sys
import pytest
from pathlib import Path

# Добавляем родительские директории в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def read_file_utf8(path):
    """Read file with UTF-8 encoding."""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class TestManagementDirective:
    """
    Tests for management directive in server.conf (O4.1, O4.2).
    """

    def test_o4_1_management_directive_exists(self):
        """
        O4.1: server.conf has management directive.
        """
        server_conf_path = Path(__file__).parent.parent.parent / "docker" / "openvpn-server" / "server.conf"
        content = read_file_utf8(server_conf_path)

        assert "management unix-socket" in content, \
            "server.conf must contain 'management unix-socket' directive"

    def test_o4_1_management_socket_path(self):
        """
        O4.1: management directive uses correct socket path.
        """
        server_conf_path = Path(__file__).parent.parent.parent / "docker" / "openvpn-server" / "server.conf"
        content = read_file_utf8(server_conf_path)

        assert "/run/openvpn/management.sock" in content, \
            "management socket must be at /run/openvpn/management.sock"

    def test_o4_2_management_before_client_config_dir(self):
        """
        O4.2: management directive is at the beginning (before client-config-dir).
        """
        server_conf_path = Path(__file__).parent.parent.parent / "docker" / "openvpn-server" / "server.conf"
        content = read_file_utf8(server_conf_path)
        
        lines = content.splitlines()
        
        management_idx = None
        client_config_dir_idx = None

        for i, line in enumerate(lines):
            # Use strip and check for exact management directive (without leading comment)
            stripped = line.strip()
            # Check if line starts with "management" (no leading spaces/comments)
            if stripped.startswith("management unix-socket"):
                management_idx = i
            # Check for actual directive line (not comment)
            elif stripped.startswith("client-config-dir"):
                client_config_dir_idx = i
                break

        assert management_idx is not None, "management directive must exist"
        assert client_config_dir_idx is not None, "client-config-dir directive must exist"
        assert management_idx < client_config_dir_idx, \
            "management directive must be BEFORE client-config-dir"


class TestEntrypointScript:
    """
    Tests for entrypoint.sh (O4.3).
    """

    def test_o4_3_mgmt_socket_dir_defined(self):
        """
        O4.3: entrypoint.sh defines socket directory variable.
        """
        entrypoint_path = Path(__file__).parent.parent.parent / "docker" / "openvpn-server" / "entrypoint.sh"
        content = read_file_utf8(entrypoint_path)

        assert "MGMT_SOCKET_DIR" in content or "MGMT_SOCKET" in content, \
            "entrypoint.sh must define MGMT_SOCKET_DIR variable"

    def test_o4_3_mgmt_socket_dir_created(self):
        """
        O4.3: entrypoint.sh creates socket directory.
        """
        entrypoint_path = Path(__file__).parent.parent.parent / "docker" / "openvpn-server" / "entrypoint.sh"
        content = read_file_utf8(entrypoint_path)

        assert "/run/openvpn" in content or 'mkdir -p "$MGMT' in content, \
            "entrypoint.sh must create /run/openvpn directory for socket"

    def test_o4_3_mgmt_socket_dir_in_main(self):
        """
        O4.3: Socket directory creation is in main() function.
        """
        entrypoint_path = Path(__file__).parent.parent.parent / "docker" / "openvpn-server" / "entrypoint.sh"
        content = read_file_utf8(entrypoint_path)

        assert 'mkdir -p' in content and 'MGMT' in content, \
            "Socket directory creation must be in main()"


class TestDockerCompose:
    """
    Tests for docker-compose.yml (O4.4).
    """

    def test_o4_4_mgmt_volume_mounted(self):
        """
        O4.4: docker-compose.yml mounts volume for management socket.
        """
        compose_path = Path(__file__).parent.parent.parent / "docker" / "docker-compose.yml"
        content = read_file_utf8(compose_path)

        assert "open_mgmt" in content or "openvpn_mgmt" in content, \
            "docker-compose.yml must mount volume for management socket"
        assert "/run/openvpn" in content, \
            "volume must mount to /run/openvpn"

    def test_o4_4_mgmt_volume_defined(self):
        """
        O4.4: Volume is defined in volumes section.
        """
        compose_path = Path(__file__).parent.parent.parent / "docker" / "docker-compose.yml"
        content = read_file_utf8(compose_path)

        assert "open_mgmt:" in content or "openvpn_mgmt:" in content, \
            "management socket volume must be defined in volumes section"


class TestConsistency:
    """
    Tests for configuration consistency.
    """

    def test_socket_path_consistency(self):
        """
        Socket path must be consistent across all files.
        """
        server_conf_path = Path(__file__).parent.parent.parent / "docker" / "openvpn-server" / "server.conf"
        entrypoint_path = Path(__file__).parent.parent.parent / "docker" / "openvpn-server" / "entrypoint.sh"
        compose_path = Path(__file__).parent.parent.parent / "docker" / "docker-compose.yml"

        server_conf = read_file_utf8(server_conf_path)
        entrypoint = read_file_utf8(entrypoint_path)
        compose = read_file_utf8(compose_path)

        assert "/run/openvpn" in server_conf, \
            "server.conf must contain /run/openvpn"
        assert "/run/openvpn" in entrypoint, \
            "entrypoint.sh must contain /run/openvpn"
        assert "/run/openvpn" in compose, \
            "docker-compose.yml must contain /run/openvpn"


class TestMgmtClientIntegration:
    """
    Tests for mgmt_client integration.
    """

    def test_mgmt_client_socket_path_matches(self):
        """
        Socket path in mgmt_client.py must match configuration.
        """
        mgmt_client_path = Path(__file__).parent.parent.parent / "collector" / "mgmt_client.py"
        server_conf_path = Path(__file__).parent.parent.parent / "docker" / "openvpn-server" / "server.conf"

        mgmt_client = read_file_utf8(mgmt_client_path)
        server_conf = read_file_utf8(server_conf_path)

        assert "/run/openvpn" in mgmt_client, \
            "mgmt_client.py must use /run/openvpn"
        assert "/run/openvpn" in server_conf, \
            "server.conf must use /run/openvpn"
