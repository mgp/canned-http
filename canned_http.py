"""A web server that accepts HTTP requests from a client, verifies that each
request contains some expected values, and returns canned responses for the
requests. The expected values in the requests and the canned responses are
specified by a script that is provided when the web server is run.

For requests, the script specifies the following parameters:
  * method (required): The HTTP method used, such as GET or POST.
  * url (required): The URL path requested.
  * headers (optional): A map of expected HTTP headers. If provided, the headers
    of a request must be a superset of these headers.

For responses, the script specifies the following parameters:
  * status_code (required): The HTTP status code to return, such as 200 or 404.
  * content_type (required): The value of the Content-Type header to return.
  * headers (optional): A map of HTTP header names and values to return in the
    response.
  * delay (optional): The number of milliseconds to wait before sending the
    response, which is useful for simulating long-polling by the server.
  * body (optional): The body of the response, such as the HTML to render in the
    browser in response to a GET request.
  * body_filename (optional): The filename whose contents should be used as the
    body of the response.
A response can be omitted altogether, which is useful for simulating
long-polling where the client must close the connection. If a response is
present, then exactly one of body and body_filename must be set. Setting both
or neither is invalid.

A request and the optional response is called an exchange. The persistent
connections feature of HTTP 1.1 allows multiple exchanges over a single TCP/IP
connection between the client and the server, provided that every exchange
except the last includes a response. An array of exchanges represents all the
exchanges across a single connection. The script is simply an array of such
arrays, so that it specifies the number of expected connections, and the order
of exchanges for each connection.

Author: Michael Parker (michael.g.parker@gmail.com)
"""

import argparse
import BaseHTTPServer
import json
import os
import SocketServer
import sys
import time


class Script:
  """A script specifying the expected requests made by the client, and the
  replies sent by the server.
  """

  def __init__(self, connections=()):
    self._connections = tuple(connections)

  def __repr__(init):
    return 'connections=%s' % repr(self._connections)


class Connection:
  """A connection from the client to the server.

  For HTTP 1.1 all connections are persistent unless declared otherwise,
  allowing multiple requests and replies over a single connection. This is
  modeled by a Connection containing a sequence of Exchange instances.
  """

  def __init__(self, exchanges=()):
    self._exchanges = tuple(exchanges)

  def __repr__(self):
    return 'exchanges=%s' % repr(self._exchanges)


class Exchange:
  """An exchange, or a request received from the client and an optional reply by
  the server.

  The server can either can either send a reply after some specified delay in
  milliseconds, or can choose to send no reply. If the server does not send a
  reply, it is the responsibility of the client to terminate the connection.
  (A typical web server will disconnect after some timeout expires, but
  well-behaved clients should also timeout and disconnect.)
  """

  @staticmethod
  def _join_parts(string_parts):
    string = ', '.join(('%s: %s' % (key, value) for (key, value) in string_parts))
    return '{%s}' % string

  class Request:
    """A request from the client to the server.

    A request must contain a HTTP method and URL. Expected headers and the
    request body, typically only used with POST or PUT, are optional.
    """
    def __init__(self, method, url, headers=None, body=None):
      self._method = method
      self._url = url
      self._headers = headers or {}
      self._body = body

    def __repr__(self):
      request_parts = [('method', self._method), ('url', self._url)]
      if self._headers:
        request_parts.append(('headers', self._headers))
      if self._body:
        request_parts.append(('body', self._body))
      return Exchange._join_parts(request_parts)

  class Response:
    """A response from the server to the client.

    A response must contain a HTTP status code, a value for the Content-Type
    header, and a body. The body is either a given string or the contents of a
    given file. Additional headers and a delay before sending the response are
    optional.
    """

    @staticmethod
    def response_with_body(status_code, content_type, body, headers=None, delay=0):
      """Returns a response with the given string as the body."""
      return Exchange.Response(status_code, content_type, delay, headers, body=body)

    @staticmethod
    def response_from_file(status_code, content_type, body_filename, headers=None,
        delay=0):
      """Returns a response with the contents of the given file as the body."""
      return Exchange.Response(status_code, content_type, delay, headers,
          body_filename=body_filename)

    def __init__(self, status_code, content_type, delay, headers=None,
        body=None, body_filename=None):
      self._status_code = status_code
      self._content_type = content_type
      self._delay = delay
      self._headers = headers
      self._body = body
      self._body_filename = body_filename

    def __repr__(self):
      response_parts = [('status_code', self._status_code),
                        ('content_type', self._content_type)]
      if self._delay:
        response_parts.append(('delay', self._delay))
      if self._headers:
        response_parts.append(('headers', repr(self._headers)))
      if self._body:
        response_parts.append(('body', self._body))
      elif self._body_filename:
        response_parts.append(('body_filename', self._body_filename))
      return Exchange._join_parts(response_parts)

  def __init__(self, request, response=None):
    self._request = request
    self._response = response

  def __repr__(self):
    if self._response:
      return '{request=%s, response=%s}' % (repr(self._request), repr(self._response))
    else:
      return '{request=%s}' % repr(self._request)


class DirectorError(Exception):
  """An exception raised if the Director encountered an unexpected request or
  event in a Script.
  """

  def __init__(self, message):
    self._message = message

  def __str__(self):
    return repr(self)

  def __repr__(self):
    return self._message


class Director:
  """Class that ensures that connections established and requests sent by the
  client follow the provided Script instance.

  If the script is not followed, a DirectorError is raised.
  """

  class _Event:
    """An event that the server expects to generate as part of the script.
    
    This class is simply to make verifying a Script easier.
    """
    _CONNECTION_OPENED = 'connection_opened'
    _CONNECTION_CLOSED = 'connection_closed'
    _GOT_REQUEST = 'got_request'

    @staticmethod
    def connection_opened_event(connection_index):
      """Returns an event for when a connection is opened."""
      return Director._Event(
          Director._Event._CONNECTION_OPENED, connection_index)

    @staticmethod
    def connection_closed_event(connection_index):
      """Returns an event for when a connection is closed."""
      return Director._Event(
          Director._Event._CONNECTION_CLOSED, connection_index)

    @staticmethod
    def exchange_event(connection_index, exchange_index, exchange):
      """Returns an event for the given exchange, or request and optional reply.
      """
      return Director._Event(
          Director._Event._GOT_REQUEST, connection_index, exchange_index, exchange)

    def __init__(self, event_type, connection_index, exchange_index=None, exchange=None):
      self._type = event_type
      self._connection_index = connection_index
      if exchange_index is not None:
        self._exchange_index = exchange_index
      if exchange is not None:
        self._exchange = exchange

  def __init__(self, script):
    self._next_event = None
    self._next_event_ready = False

    # Convert the given Script into a sequence of DirectorEvent instances.
    events = []
    for connection_index, connection in enumerate(script._connections, 1):
      events.append(
          Director._Event.connection_opened_event(connection_index))
      for exchange_index, exchange in enumerate(connection._exchanges, 1):
        events.append(
            Director._Event.exchange_event(connection_index, exchange_index, exchange))
      events.append(
          Director._Event.connection_closed_event(connection_index))
    self._events_iter = iter(events)

  def _ready_next_event(self):
    if not self._next_event_ready:
      try:
        self._next_event = next(self._events_iter)
      except StopIteration:
        # The last event has been reached.
        self._next_event = None
      self._next_event_ready = True

  def _finish_current_event(self):
    self._next_event_ready = False

  def connection_opened(self):
    """Called by the web server when the client opens a connection."""

    self._ready_next_event()
    if self._next_event is None:
      raise DirectorError('Client opened a connection after the script ended.')
    self._finish_current_event()

  def connection_closed(self):
    """Called by the web server when the client closes the connection.""" 

    self._ready_next_event()
    if self._next_event._type == Director._Event._GOT_REQUEST:
      raise DirectorError(
          'Client closed the connection %s instead of performing exchange %s' %
          (self._next_event._connection_index, self._next_event._exchange_index))
    self._finish_current_event()

  def _lowercase_headers(self, headers):
    return dict(((key.lower(), value.lower()) for (key, value) in headers))

  def got_request(self, method, url, headers={}, body=None):
    """Called by the web server when the client sends an HTTP request.
    
    Returns a tuple containing the delay and the reply to send back. If the
    reply is None, then the delay is irrelevant and the server should wait for
    the client to close the connection.
    """

    self._ready_next_event()
    if self._next_event._type == Director._Event._CONNECTION_CLOSED:
      raise DirectorError(
          "Client sent request with method '%s' and URL '%s' instead of closing connection %s" %
          (method, url, self._next_event._connection_index))

    exchange = self._next_event._exchange
    request = exchange._request
    # Assert that the method is correct.
    if method != request._method:
      raise DirectorError(
          "Expected 'method' value '%s', received '%s' for connection %s, exchange %s" %
          (request._method, method, self._next_event._connection_index,
           self._next_event._exchange_index))
    # Assert that the URL is correct.
    if url != request._url:
      raise DirectorError(
          "Expected 'url' value '%s', received '%s' for connection %s, exchange %s" %
          (request._url, url, self._next_event._connection_index,
           self._next_event._exchange_index))
    # Assert that the optional body is correct.
    if body != request._body:
      raise DirectorError(
          "Expected 'body' value '%s', received '%s' for connection %s, exchange %s" %
          (request._body, body, self._next_event._connection_index,
           self._next_event._exchange_index))
    # Assert that the headers are correct.
    expected_headers = self._lowercase_headers(request._headers)
    for header_name, expected_header_value in expected_headers.iteritems():
      header_value = headers.get(header_name, None)
      if header_value:
        header_value = header_value.lower()
      if expected_header_value != header_value:
        raise DirectorError(
            "Expected value '%s' for header name '%s', "
            "received '%s' for connection %s, exchange %s" %
            (expected_header_value, header_name, header_value, i, j))

    self._finish_current_event()
    return exchange._response

  def is_done(self):
    """Returns whether the script has been fully run by the client."""

    self._ready_next_event()
    return self._next_event is None


class ScriptParseError(Exception):
  """An exception raised if elements of a Script could not be parsed."""

  def __init__(self, message):
    self._message = message

  def __str__(self):
    return repr(self)

  def __repr__(self):
    return self._message


def script_from_data(script_data):
  """Returns a Script instance parsed from the given Python objects.
  """

  connections = []
  for i, connection_data in enumerate(script_data, 1):
    exchanges = []
    reached_no_reply = False
    for j, exchange_data in enumerate(connection_data, 1):
      if reached_no_reply:
        raise ScriptParseError(
            "Reply missing for exchange preceding connection %s, exchange %s" % (i, j))

      request_yaml = exchange_data.get('request', None)
      if request_yaml is None:
        raise ScriptParseError(
            "Missing 'request' key for connection %s, exchange %s" % (i, j))
      # Get and validate the required method.
      method = request_yaml.get('method', None)
      if method is None:
        raise ScriptParseError(
            "Missing 'method' key for request in connection %s, exchange %s" % (i, j))
      method_upper = method.upper()
      if method_upper not in ('GET', 'PUT', 'POST', 'DELETE'):
        raise ScriptParseError(
            "Invalid method '%s' for request in connection %s, exchange %s" % (method, i, j))
      # Get the required URL.
      url = request_yaml.get('url', None)
      if not url:
        raise ScriptParseError(
            "Missing 'url' key for request in connection %s, exchange %s" % (i, j))
      # Get the optional headers and body.
      headers = request_yaml.get('headers', {})
      body = request_yaml.get('body', None)
      # Create the request.
      request = Exchange.Request(method, url, headers, body)

      response_yaml = exchange_data.get('response', None)
      if response_yaml:
        # Get the required status code.
        status_code = response_yaml.get('status_code', None)
        if not status_code:
          raise ScriptParseError(
              "Missing 'status_code' key for response in connection %s, exchange %s" % (i, j))
        # Get the required content type.
        content_type = response_yaml.get('content_type', None)
        if not content_type:
          raise ScriptParseError(
              "Missing 'content_type' key for response in connection %s, exchange %s" % (i, j))
        # Get the optional headers and delay.
        headers = response_yaml.get('headers', {})
        delay = response_yaml.get('delay', 0)

        body = response_yaml.get('body', None)
        body_filename = response_yaml.get('body_filename', None)
        if body and body_filename:
          raise ScriptParseError(
              "Found both 'body' and 'body_filename' keys for response in "
              "connection %s, exchange %s" % (i, j))
        elif body:
          # Create the response with the given body.
          response = Exchange.Response.response_with_body(
              status_code, content_type, body, headers, delay)
        elif body_filename:
          # Create the response with a body from the given filename.
          response = Exchange.Response.response_from_file(
              status_code, content_type, body_filename, headers, delay)
        else:
          raise ScriptParseError(
              "Missing both 'body' and 'body_filename' keys for response in "
              "connection %s, exchange %s" % (i, j))
      else:
        # There is no response for this request.
        reached_no_reply = True
        response = None

      exchange = Exchange(request, response)
      exchanges.append(exchange)

    connection = Connection(exchanges)
    connections.append(connection)

  return Script(connections)

def script_from_json_string(json_string):
  """Returns a Script instance parsed from the given string containing JSON.
  """

  raw_json = json.loads(json_string)
  if not raw_json:
    raw_json = []
  return script_from_data(raw_json)

def script_from_yaml_string(yaml_string):
  """Returns a Script instance parsed from the given string containing YAML.
  """

  # The PyYAML library, see http://pyyaml.org/
  import yaml

  raw_yaml = yaml.safe_load(yaml_string)
  if not raw_yaml:
    raw_yaml = []
  return script_from_data(raw_yaml)

def script_from_json_file(json_filename):
  """Reads the contents of the given filename and returns a Script instance
  parsed from the contained JSON.
  """

  f = open(json_filename, 'r')
  json_string = f.read()
  f.close()
  return script_from_json_string(json_string)

def script_from_yaml_file(yaml_filename):
  """Reads the contents of the given filename and returns a Script instance
  parsed from the contained YAML.
  """

  f = open(yaml_filename, 'r')
  yaml_string = f.read()
  f.close()
  return script_from_yaml_string(yaml_string)


class DirectorRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
  """A request handler that uses the given Director instance to verify the
  script.
  """

  @staticmethod
  def set_director(director):
    """Sets the director for use over the lifetime of the web server."""
    DirectorRequestHandler._director = director

    DirectorRequestHandler._script_error = False
    DirectorRequestHandler._script_done = False

  def setup(self):
    BaseHTTPServer.BaseHTTPRequestHandler.setup(self)

    # Allow persistent connections.
    self.protocol_version = 'HTTP/1.1'

  def handle_request(self):
    # Get the HTTP method and URL of the request.
    method = self.command
    url = self.path
    headers = self.headers
    # Get the body of the request.
    content_length = self.headers.get('Content-Length', None)
    if content_length:
      content_length = int(content_length)
      body = self.rfile.read(content_length)
      if not body:
        body = None
    else:
      body = None

    response = DirectorRequestHandler._director.got_request(method, url, headers, body)

    if response:
      time.sleep(response._delay)

      # Get the body of the response.
      if response._body:
        body = response._body
        file_size = len(body)
      else:
        f = open(response._body_filename, 'rb')
        fs = os.fstat(f.fileno())
        body = f.read()
        file_size = fs.st_size
        f.close()

      # Send the headers of the response.
      self.send_response(response._status_code)
      self.send_header('Content-Type', response._content_type)
      self.send_header('Content-Length', file_size)
      for header_name, header_value in response._headers:
        self.send_header(header_name, header_value)
      self.end_headers()

      # Send the body to conclude the response.
      self.wfile.write(body)

    DirectorRequestHandler._script_done = DirectorRequestHandler._director.is_done()

  def do_GET(self):
    self.handle_request()

  def do_POST(self):
    self.handle_request()

  def do_PUT(self):
    self.handle_request()

  def do_DELETE(self):
    self.handle_request()

  def handle(self):
    try:
      DirectorRequestHandler._director.connection_opened()
      BaseHTTPServer.BaseHTTPRequestHandler.handle(self)
      DirectorRequestHandler._director.connection_closed()
      DirectorRequestHandler._script_done = DirectorRequestHandler._director.is_done()
    except DirectorError as e:
      # Exceptions raised from handle_request will also be caught here.
      print >> sys.stderr, 'ERROR: ', repr(e)
      DirectorRequestHandler._script_error = True

if __name__ == '__main__':
  arg_parser = argparse.ArgumentParser()
  arg_parser.add_argument('--port', type=int, required=False, default=8080,
      help='Port the web server should run on')
  arg_parser.add_argument('--json_filename', type=str, required=False, default='',
      help='JSON input file for expected requests and replies')
  arg_parser.add_argument('--yaml_filename', type=str, required=False, default='',
      help='YAML input file for expected requests and replies')
  parsed_args = arg_parser.parse_args()

  # Create the script from the provided filename.
  if parsed_args.json_filename and parsed_args.yaml_filename:
    print >> sys.stderr, 'Cannot specify both --json_filename and --yaml_filename.'
    sys.exit(0)
  elif parsed_args.json_filename:
    script = script_from_json_file(parsed_args.json_filename)
  elif parsed_args.yaml_filename:
    script = script_from_yaml_file(parsed_args.yaml_filename)
  else:
    print >> sys.stderr, 'Must specify either --json_filename or --yaml_filename.'
    sys.exit(0)

  # Create the Director instance and begin serving.
  director = Director(script)
  DirectorRequestHandler.set_director(director)
  # Serve on the specified port until the script is finished or not followed.
  server = SocketServer.TCPServer(("", parsed_args.port), DirectorRequestHandler)
  while (not DirectorRequestHandler._script_done and
         not DirectorRequestHandler._script_error):
    server.handle_request()

