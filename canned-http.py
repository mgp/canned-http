"""TODO

Author: Michael Parker (michael.g.parker@gmail.com)
"""

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

  @staticmethod
  def script_reply(method, url, reply, body=None, delay=0):
    """Returns an Exchange instance where the server sends the given reply after
    the given delay in milliseconds."""
    return Exchange(method, url, body, delay)

  @staticmethod
  def script_no_reply(method, url, body=None):
    """Returns an Exchange instance where the server sends no reply and so the
    client must disconnect.
    """
    return Exchange(method, url, body)

  def __init__(self, method, url, body=None, delay=0, reply=None):
    self._method = method
    self._url = url
    self._body = body
    self._delay = delay
    self._reply = reply

  def __repr__(self):
    request_parts = [('method', self._method), ('url', self._url)]
    if self._body:
      request_parts.append(('body', self._body))
    request = ', '.join(('%s=%s' % (key, value) for (key, value) in request_parts))
    if not self._reply:
      return '{request={%s}, no_reply}' % request
    else
      return '{request={%s}, delay=%s, reply=%s}' % (request, self._delay, self._reply)


class DirectorException(Exception):
  """An exception raised if the Director encountered an unexpected request or
  event in a Script."""

  def __init__(self, message):
    self._message = message

  def __repr__(self):
    return message


class Director:
  """Class that ensures that connections established and requests sent by the
  client follow the provided Script instance.

  If the script is not followed, a DirectorException is raised.
  """

  class _DirectorEvent:
    """An event that the server expects to generate as part of the script.
    
    This class is simply to make verifying a Script easier.
    """
    _CONNECTION_OPENED = 'connection_opened'
    _CONNECTION_CLOSED = 'connection_closed'
    _GOT_REQUEST = 'got_request'

    @staticmethod
    def connection_opened_event(connection_index):
      return _DirectorEvent(_DirectorEvent._CONNECTION_OPENED, connection_index)

    @staticmethod
    def connection_closed_event(connection_index):
      return _DirectorEvent(_DirectorEvent._CONNECTION_CLOSED, connection_index)

    @staticmethod
    def exchange_event(connection_index, exchange_index, exchange):
      return _DirectorEvent(
          _DirectorEvent._GOT_REQUEST, connection_index, exchange_index, exchange)

    def __init__(self, event_type, connection_index, exchange_index=None, exchange=None):
      self._event_type = event_type
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
      self._events.append(
          _DirectorEvent.connection_opened_event(connection_index))
      for exchange_index, exchange in enumerate(connection._exchanges, 1):
        self._events.append(
            _DirectorEvent(connection_index, exchange_index, exchange)
      self._events.append(
          _DirectorEvent.connection_closed_event(connection_index))
    self._events_iter = iter(events)

  def _ready_next_event(self):
    if not self._next_event_ready:
      try:
        self._next_event = next(events_iter)
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
    if self._next_event.type == _DirectorEvent._GOT_REQUEST:
      raise DirectorException(
          'Client closed the connection %s instead of performing exchange %s' %
          (self._next_event._connection_index, self._next_event._exchange_index))
    self._finish_current_event()

  def got_request(method, url, body):
    """Called by the web server when the client sends an HTTP request.
    
    Returns a tuple containing the delay and the reply to send back. If the
    reply is None, then the delay is irrelevant and the server should wait for
    the client to close the connection.
    """

    self._ready_next_request()
    if self._next_event.type == _DirectorEvent._CONNECTION_CLOSED:
      raise DirectorException(
          'Client sent request with method %s and URL %s instead of closing connection %s' %
          (method, url, self._next_event._connection_index))

    if method != self._event._method:
      raise DirectorException(
          "Expected 'method' value %s, received %s for connection %s, exchange %s" %
          (self._event._method, method, self._event._connection_index,
           self._event._exchange_index))
    if url != self._event._url:
      raise DirectorException(
          "Expected 'url' value %s, received %s for connection %s, exchange %s" %
          (self._event._url, url, self._event._connection_index,
           self._event._exchange_index))
    if body != self._event._body:
      raise DirectorException(
          "Expected 'body' value %s, received %s for connection %s, exchange %s" %
          (self._event._body, body, self._event._connection_index,
           self._event._exchange_index))

    self._finish_current_event()
    return (self._event.delay, self._event.reply)

  def is_done(self):
    """Returns whether the script has been fully run by the client."""

    self._ready_next_event()
    return self._next_event is None


class YamlParseError(Exception):
  """An exception raised if elements of a Script could not be parsed from YAML.
  """

  def __init__(self, message):
    self._message = message

  def __repr__(self):
    return message


def parse_yaml(raw_yaml):
  """Returns a Script instance parsed from the given string containing YAML.
  """

  connections = []
  for i, connection_yaml in enumerate(raw_yaml, 1):
    exchanges = []
    reached_no_reply = False
    for j, exchange_yaml in enumerate(connection_yaml, 1):
      # Get and validate the required method.
      method = exchange_yaml.get('method', None)
      if method is None:
        raise YamlParseError(
            "Missing 'method' key for connection %s, exchange %s" % (i, j))
      method_upper = method.upper()
      if method_upper not in ('GET', 'PUT', 'POST', 'DELETE'):
        raise YamlParseError(
            "Invalid method '%s' for connection %s, exchange %s" % (i, j))
      # Get and validate the required URL.
      url = exchange_yaml.get('url', None)
      if not url:
        raise YamlParseError(
            "Missing 'url' key for connection %s, exchange %s" % (i, j))
      # Get the optional body.
      body = exchange_yaml.get('body', None)

      # Get the optional reply.
      reply = exchange_yaml.get('reply')
      if reply:
        # Send the reply after the given delay in milliseconds.
        delay = exchange_yaml.get('delay', 0)
      else:
        # The client must close the connection.
        exchange = Exchange.script_no_reply(method, url, body)
        reached_no_reply = True
      exchanges.append(exchange)

    connection = Connection(exchanges)
    connections.append(connection)

  return Script(connections)

def parse_yaml_from_file(yaml_filename):
  """Reads the contents of the given filename and returns a Script instance
  parsed from the contained YAML.
  """

  f = open(yaml_filename, 'r')
  raw_yaml = f.read()
  f.close()
  parse_yaml(raw_yaml)


if __name__ == '__main__':
  arg_parser = argparse.ArgumentParser()
  arg_parser.add_argument('--port', type=int, required=False,
      help='Port the web server should run on')
  arg_parser.add_argument('--yaml_filename', type=str, required=True,
      help='YAML input file for expected requests and replies')
  parsed_args = arg_parser.parse_args()

  script = parse_yaml_from_file(parsed_args.yaml_filename)
  # TODO: Run the script.

