"""TODO

Author: Michael Parker (michael.g.parker@gmail.com)
"""

import argparse
import BaseHTTPServer
import SocketServer
import time

import yaml


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

  The request by the client must contain a valid HTTP method and URL. The body,
  typically only used with POST or PUT, is optional.

  The server can either can either send a reply after some specified delay in
  milliseconds, or can choose to send no reply. If the server does not send a
  reply, it is the responsibility of the client to terminate the connection.
  (A typical web server will disconnect after some timeout expires, but
  well-behaved clients should also timeout and disconnect.)
  """

  class Request:
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
      request_str = ', '.join(('%s: %s' % (key, value) for (key, value) in request_parts))
      return '{%s}' % request_str

  class Response:
    @staticmethod
    def response_with_body(status_code, content_type, body, headers=None, delay=0):
      return Exchange.Response(status_code, content_type, delay, headers, body=body)

    @staticmethod
    def response_from_file(status_code, content_type, body_filename, headers=None,
        delay=0):
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
      # TODO
      return ''

  def __init__(self, request, response=None):
    self._request = request
    self._response = response

  def __repr__(self):
    if self._response:
      return '{request=%s, response=%s}' % (repr(self._request), repr(self._response))
    else:
      return '{request=%s}' % repr(self._request)


class DirectorException(Exception):
  """An exception raised if the Director encountered an unexpected request or
  event in a Script."""

  def __init__(self, message):
    self._message = message

  def __str__(self):
    return repr(self)

  def __repr__(self):
    return self._message


class Director:
  """Class that ensures that connections established and requests sent by the
  client follow the provided Script instance.

  If the script is not followed, a DirectorException is raised.
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
      return Director._Event(
          Director._Event._CONNECTION_OPENED, connection_index)

    @staticmethod
    def connection_closed_event(connection_index):
      return Director._Event(
          Director._Event._CONNECTION_CLOSED, connection_index)

    @staticmethod
    def exchange_event(connection_index, exchange_index, exchange):
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
      raise DirectorException('Client opened a connection after the script ended.')
    self._finish_current_event()

  def connection_closed(self):
    """Called by the web server when the client closes the connection.""" 

    self._ready_next_event()
    if self._next_event._type == Director._Event._GOT_REQUEST:
      raise DirectorException(
          'Client closed the connection %s instead of performing exchange %s' %
          (self._next_event._connection_index, self._next_event._exchange_index))
    self._finish_current_event()

  def got_request(self, method, url, body=None):
    """Called by the web server when the client sends an HTTP request.
    
    Returns a tuple containing the delay and the reply to send back. If the
    reply is None, then the delay is irrelevant and the server should wait for
    the client to close the connection.
    """

    self._ready_next_event()
    if self._next_event._type == Director._Event._CONNECTION_CLOSED:
      raise DirectorException(
          'Client sent request with method %s and URL %s instead of closing connection %s' %
          (method, url, self._next_event._connection_index))

    exchange = self._next_event._exchange
    if method != exchange._method:
      raise DirectorException(
          "Expected 'method' value %s, received %s for connection %s, exchange %s" %
          (exchange._method, method, self._next_event._connection_index,
           self._next_event._exchange_index))
    if url != exchange._url:
      raise DirectorException(
          "Expected 'url' value %s, received %s for connection %s, exchange %s" %
          (exchange._url, url, self._next_event._connection_index,
           self._next_event._exchange_index))
    if body != exchange._body:
      raise DirectorException(
          "Expected 'body' value %s, received %s for connection %s, exchange %s" %
          (exchange._body, body, self._next_event._connection_index,
           self._next_event._exchange_index))

    self._finish_current_event()
    return (exchange._delay, exchange._reply)

  def is_done(self):
    """Returns whether the script has been fully run by the client."""

    self._ready_next_event()
    return self._next_event is None


class YamlParseError(Exception):
  """An exception raised if elements of a Script could not be parsed from YAML.
  """

  def __init__(self, message):
    self._message = message

  def __str__(self):
    return repr(self)

  def __repr__(self):
    return self._message


def parse_yaml(raw_yaml):
  """Returns a Script instance parsed from the given Python object containing YAML.
  """

  connections = []
  for i, connection_yaml in enumerate(raw_yaml, 1):
    exchanges = []
    reached_no_reply = False
    for j, exchange_yaml in enumerate(connection_yaml, 1):
      if reached_no_reply:
        raise YamlParseError(
            "Reply missing for exchange preceding connection %s, exchange %s" % (i, j))

      request_yaml = exchange_yaml.get('request', None)
      if request_yaml is None:
        raise YamlParseError(
            "Missing 'request' key for connection %s, exchange %s" % (i, j))
      # Get and validate the required method.
      method = request_yaml.get('method', None)
      if method is None:
        raise YamlParseError(
            "Missing 'method' key for request in connection %s, exchange %s" % (i, j))
      method_upper = method.upper()
      if method_upper not in ('GET', 'PUT', 'POST', 'DELETE'):
        raise YamlParseError(
            "Invalid method '%s' for request in connection %s, exchange %s" % (method, i, j))
      # Get the required URL.
      url = request_yaml.get('url', None)
      if not url:
        raise YamlParseError(
            "Missing 'url' key for request in connection %s, exchange %s" % (i, j))
      # Get the optional headers and body.
      headers = request_yaml.get('headers', {})
      body = request_yaml.get('body', None)
      # Create the request.
      request = Exchange.Request(method, url, headers, body)

      response_yaml = exchange_yaml.get('response', None)
      if response_yaml:
        # Get the required status code.
        status_code = response_yaml.get('status_code', None)
        if not status_code:
          raise YamlParseError(
              "Missing 'status_code' key for response in connection %s, exchange %s" % (i, j))
        # Get the required content type.
        content_type = response_yaml.get('content_type', None)
        if not content_type:
          raise YamlParseError(
              "Missing 'content_type' key for response in connection %s, exchange %s" % (i, j))
        # Get the optional headers and delay.
        headers = response_yaml.get('headers', {})
        delay = response_yaml.get('delay', 0)

        body = response_yaml.get('body', None)
        body_filename = response_yaml.get('body_filename', None)
        if body and body_filename:
          raise YamlParseError(
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
          raise YamlParseError(
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

def parse_yaml_from_string(yaml_string):
  """Returns a Script instance parsed from the given string containing YAML.
  """

  raw_yaml = yaml.safe_load(yaml_string)
  if not raw_yaml:
    raw_yaml = []
  return parse_yaml(raw_yaml)

def parse_yaml_from_file(yaml_filename):
  """Reads the contents of the given filename and returns a Script instance
  parsed from the contained YAML.
  """

  f = open(yaml_filename, 'r')
  yaml_string = f.read()
  f.close()
  return parse_yaml_from_string(yaml_string)


class DirectorRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
  @staticmethod
  def set_director(director):
    DirectorRequestHandler._director = director

  def handle_request(self):
    method = self.command
    url = self.path
    content_length = self.headers.get('Content-Length', None)
    if content_length:
      content_length = int(content_length)
      body = self.rfile.read(content_length)
      if not body:
        body = None
    else:
      body = None

    delay, reply = DirectorRequestHandler._director.got_request(method, url, body)
    if reply:
      time.sleep(delay)
      self.send_header('Content-type:', 'text/html; charset=utf-8')
      self.send_response(200, reply)

  def do_GET(self):
    self.handle_request()

  def do_POST(self):
    self.handle_request()

  def do_PUT(self):
    self.handle_request()

  def do_DELETE(self):
    self.handle_request()

  def handle(self):
    DirectorRequestHandler._director.connection_opened()
    BaseHTTPServer.BaseHTTPRequestHandler.handle(self)
    DirectorRequestHandler._director.connection_closed()


if __name__ == '__main__':
  arg_parser = argparse.ArgumentParser()
  arg_parser.add_argument('--port', type=int, required=False, default=8080,
      help='Port the web server should run on')
  arg_parser.add_argument('--yaml_filename', type=str, required=True,
      help='YAML input file for expected requests and replies')
  arg_parser.add_argument('--quit_on_failure', type=bool, required=False, default=True,
      help='Quit if the client does not follow the script')
  parsed_args = arg_parser.parse_args()

  # Create the script and a Director instance from the script.
  script = parse_yaml_from_file(parsed_args.yaml_filename)
  director = Director(script)
  DirectorRequestHandler.set_director(director)
  # Begin serving on the specified port.
  server = SocketServer.TCPServer(("", parsed_args.port), DirectorRequestHandler)
  server.serve_forever()

