import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest
import requests

import pkgpanda.util
from pkgpanda import UserManagement
from pkgpanda.exceptions import ValidationError


def test_variant_variations():
    assert pkgpanda.util.variant_str(None) == ''
    assert pkgpanda.util.variant_str('test') == 'test'

    assert pkgpanda.util.variant_object('') is None
    assert pkgpanda.util.variant_object('test') == 'test'

    assert pkgpanda.util.variant_name(None) == '<default>'
    assert pkgpanda.util.variant_name('test') == 'test'

    assert pkgpanda.util.variant_prefix(None) == ''
    assert pkgpanda.util.variant_prefix('test') == 'test.'


def test_validate_username():

    def good(name):
        UserManagement.validate_username(name)

    def bad(name):
        with pytest.raises(ValidationError):
            UserManagement.validate_username(name)

    good('dcos_mesos')
    good('dcos_a')
    good('dcos__')
    good('dcos_a_b_c')
    good('dcos_diagnostics')
    good('dcos_a1')
    good('dcos_1')

    bad('dcos')
    bad('d')
    bad('d_a')
    bad('foobar_asdf')
    bad('dcos_***')
    bad('dc/os_foobar')
    bad('dcos_foo:bar')
    bad('3dcos_foobar')
    bad('dcos3_foobar')


def test_validate_group():
    # assuming linux distributions have `root` group.
    UserManagement.validate_group('root')

    with pytest.raises(ValidationError):
        UserManagement.validate_group('group-should-not-exist')


def test_split_by_token():
    split_by_token = pkgpanda.util.split_by_token

    # Token prefix and suffix must not be empty.
    with pytest.raises(ValueError):
        list(split_by_token('', ')', 'foo'))
    with pytest.raises(ValueError):
        list(split_by_token('(', '', 'foo'))
    with pytest.raises(ValueError):
        list(split_by_token('', '', 'foo'))

    # Empty string.
    assert list(split_by_token('{{ ', ' }}', '')) == [('', False)]

    # String with no tokens.
    assert list(split_by_token('{{ ', ' }}', 'no tokens')) == [('no tokens', False)]

    # String with one token.
    assert list(split_by_token('{{ ', ' }}', '{{ token_name }}')) == [('{{ token_name }}', True)]
    assert list(split_by_token('{{ ', ' }}', 'foo {{ token_name }}')) == [('foo ', False), ('{{ token_name }}', True)]
    assert list(split_by_token('{{ ', ' }}', '{{ token_name }} foo')) == [('{{ token_name }}', True), (' foo', False)]

    # String with multiple tokens.
    assert list(split_by_token('{{ ', ' }}', 'foo {{ token_a }} bar {{ token_b }} \n')) == [
        ('foo ', False), ('{{ token_a }}', True), (' bar ', False), ('{{ token_b }}', True), (' \n', False)
    ]

    # Token decoration is stripped when requested.
    assert list(split_by_token('[[', ']]', 'foo [[token_a]] bar[[token_b ]]', strip_token_decoration=True)) == [
        ('foo ', False), ('token_a', True), (' bar', False), ('token_b ', True)
    ]

    # Token prefix and suffix can be the same.
    assert list(split_by_token('||', '||', 'foo ||token_a|| bar ||token_b|| \n')) == [
        ('foo ', False), ('||token_a||', True), (' bar ', False), ('||token_b||', True), (' \n', False)
    ]
    assert list(split_by_token('||', '||', 'foo ||token_a|| bar ||token_b|| \n', strip_token_decoration=True)) == [
        ('foo ', False), ('token_a', True), (' bar ', False), ('token_b', True), (' \n', False)
    ]

    # Missing token suffix.
    with pytest.raises(Exception):
        list(split_by_token('(', ')', '(foo) (bar('))
    # Missing suffix for middle token.
    with pytest.raises(Exception):
        list(split_by_token('[[', ']]', '[[foo]] [[bar [[baz]]'))
    # Missing token prefix.
    with pytest.raises(Exception):
        list(split_by_token('[[', ']]', 'foo]] [[bar]]'))
    # Nested tokens.
    with pytest.raises(Exception):
        list(split_by_token('[[', ']]', '[[foo]] [[bar [[baz]] ]]'))

    # Docstring examples.
    assert list(split_by_token('{', '}', 'some text {token} some more text')) == [
        ('some text ', False), ('{token}', True), (' some more text', False)
    ]
    assert list(split_by_token('{', '}', 'some text {token} some more text', strip_token_decoration=True)) == [
        ('some text ', False), ('token', True), (' some more text', False)
    ]


def test_write_string(tmpdir):
    """
    `pkgpanda.util.write_string` writes or overwrites a file with permissions
    for User to read and write, Group to read and Other to read.

    Permissions of the given filename are preserved, or a new file is created
    with 0o644 permissions.

    This test was written to make current functionality regression-safe which
    is why no explanation is given for these particular permission
    requirements.
    """
    filename = os.path.join(str(tmpdir), 'foo_filename')
    pkgpanda.util.write_string(filename=filename, data='foo_contents')
    with open(filename) as f:
        assert f.read() == 'foo_contents'

    pkgpanda.util.write_string(filename=filename, data='foo_contents_2')
    with open(filename) as f:
        assert f.read() == 'foo_contents_2'

    st_mode = os.stat(filename).st_mode
    expected_permission = 0o644
    assert (st_mode & 0o777) == expected_permission

    os.chmod(filename, 0o777)
    pkgpanda.util.write_string(filename=filename, data='foo_contents_3')
    with open(filename) as f:
        assert f.read() == 'foo_contents_3'
    st_mode = os.stat(filename).st_mode
    expected_permission = 0o777
    assert (st_mode & 0o777) == expected_permission


class MockDownloadServerRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b'foobar'

        self.send_response(requests.codes.ok)
        self.send_header('Content-Type', 'text/plain')

        if 'no_content_length' not in self.path:
            self.send_header('Content-Length', '6')

        self.end_headers()

        if self.server.requests_received == 0:
            # Don't send the last byte of the response body.
            self.wfile.write(body[:len(body) - 1])
        else:
            self.wfile.write(body)
        self.server.requests_received += 1

        return


class MockHTTPDownloadServer(HTTPServer):
    requests_received = 0

    def reset_requests_received(self):
        self.requests_received = 0


@pytest.fixture(scope='module')
def mock_download_server():
    mock_server = MockHTTPDownloadServer(('localhost', 0), MockDownloadServerRequestHandler)

    mock_server_thread = Thread(target=mock_server.serve_forever, daemon=True)
    mock_server_thread.start()

    return mock_server


def test_download_remote_file(tmpdir, mock_download_server):
    mock_download_server.reset_requests_received()

    url = 'http://localhost:{port}/foobar.txt'.format(port=mock_download_server.server_port)

    out_file = os.path.join(str(tmpdir), 'foobar.txt')
    response = pkgpanda.util._download_remote_file(out_file, url)

    response_is_ok = response.ok
    assert response_is_ok

    assert mock_download_server.requests_received == 2

    with open(out_file, 'rb') as f:
        assert f.read() == b'foobar'


def test_download_remote_file_without_content_length(tmpdir, mock_download_server):
    mock_download_server.reset_requests_received()

    url = 'http://localhost:{port}/foobar.txt?no_content_length=true'.format(
        port=mock_download_server.server_port)

    out_file = os.path.join(str(tmpdir), 'foobar.txt')
    response = pkgpanda.util._download_remote_file(out_file, url)

    response_is_ok = response.ok
    assert response_is_ok

    assert mock_download_server.requests_received == 1

    with open(out_file, 'rb') as f:
        assert f.read() == b'fooba'
