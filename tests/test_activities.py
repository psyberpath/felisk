"""
Felisk — Activity Unit Tests
Tests socket-based activities with mocked network calls.
Validates correct command formatting and error handling.
"""

from unittest.mock import patch, MagicMock

import pytest
from temporalio.exceptions import ApplicationError

from temporal_engine.activities import (
    PicoCommand,
    _send_to_pico,
    PICO_IP,
    PICO_PORT,
)


class TestSendToPico:
    """Tests for the _send_to_pico helper function."""

    @patch("temporal_engine.activities.socket.socket")
    def test_successful_send(self, mock_socket_class):
        """Should send HTTP GET and return response body."""
        mock_sock = MagicMock()
        mock_socket_class.return_value.__enter__ = MagicMock(return_value=mock_sock)
        mock_socket_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_sock.recv.return_value = b'HTTP/1.1 200 OK\r\n\r\n{"status":"executed"}'

        result = _send_to_pico("ACCESS_APPROVED")

        mock_sock.connect.assert_called_once_with((PICO_IP, PICO_PORT))
        sent_data = mock_sock.sendall.call_args[0][0].decode("utf-8")
        assert "GET /api/command?value=ACCESS_APPROVED" in sent_data
        assert "executed" in result

    @patch("temporal_engine.activities.socket.socket")
    def test_connection_refused_raises_non_retryable(self, mock_socket_class):
        """Should raise non-retryable ApplicationError on socket failure."""
        mock_sock = MagicMock()
        mock_socket_class.return_value.__enter__ = MagicMock(return_value=mock_sock)
        mock_socket_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_sock.connect.side_effect = OSError("[Errno 61] Connection refused")

        with pytest.raises(ApplicationError) as exc_info:
            _send_to_pico("LOCK_CAPTURE")

        assert exc_info.value.non_retryable is True
        assert "LOCK_CAPTURE" in str(exc_info.value)

    @patch("temporal_engine.activities.socket.socket")
    def test_timeout_raises_non_retryable(self, mock_socket_class):
        """Should raise non-retryable ApplicationError on socket timeout."""
        import socket as real_socket

        mock_sock = MagicMock()
        mock_socket_class.return_value.__enter__ = MagicMock(return_value=mock_sock)
        mock_socket_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_sock.connect.side_effect = real_socket.timeout("timed out")

        with pytest.raises(ApplicationError) as exc_info:
            _send_to_pico("SAFE_RELEASE")

        assert exc_info.value.non_retryable is True


class TestPicoCommandDataclass:
    """Tests for PicoCommand dataclass."""

    def test_default_description(self):
        cmd = PicoCommand(command="TEST")
        assert cmd.command == "TEST"
        assert cmd.description == ""

    def test_custom_description(self):
        cmd = PicoCommand(command="LOCK_CAPTURE", description="TNR lock")
        assert cmd.command == "LOCK_CAPTURE"
        assert cmd.description == "TNR lock"
