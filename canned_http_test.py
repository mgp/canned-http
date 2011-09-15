import unittest

import canned_http

class TestParseYaml(unittest.TestCase):
  def _assert_exchange(self, exchange, method, url, body=None, reply=None, delay=0):
    # Assert that the required values are correct.
    self.assertEqual(method, exchange._method)
    self.assertEqual(url, exchange._url)
    # Assert that the optional values are correct.
    try:
      exchange_body = exchange._body
      self.assertEqual(body, exchange_body)
    except AttributeError:
      self.assertIsNone(body)
    try:
      exchange_reply = exchange._reply
      exchange_delay = exchange._delay
      self.assertEqual(reply, exchange_reply)
      self.assertEqual(delay, exchange_delay)
    except AttributeError:
      self.assertIsNone(reply)

  def test_invalid_script(self):
    # Raise exception if method is missing.
    raw_yaml = """
        - - url: /foo.html
            reply: <html><body></body></html>
        """
    with self.assertRaises(canned_http.YamlParseError):
      canned_http.parse_yaml_from_string(raw_yaml)
    # Raise exception if method is invalid.
    raw_yaml = """
        - - method: PONY
            url: /foo.html
            reply: <html><body></body></html>
        """
    with self.assertRaises(canned_http.YamlParseError):
      canned_http.parse_yaml_from_string(raw_yaml)
    # Raise exception if url is missing.
    raw_yaml = """
        - - method: GET
            reply: <html><body></body></html>
        """
    with self.assertRaises(canned_http.YamlParseError):
      canned_http.parse_yaml_from_string(raw_yaml)
    # Raise exception if reply is missing for exchange that is not last.
    raw_yaml = """
        - - method: GET
            url: /foo1.html
          - method: GET
            url: /foo2.html
            reply: <html><body></body></html>
        """
    with self.assertRaises(canned_http.YamlParseError):
      canned_http.parse_yaml_from_string(raw_yaml)

  def test_method_capitalization(self):
    # Capitalization of method should not matter.
    method = 'PuT'
    url = '/foo.html'
    reply = '<html><body></body></html>'
    raw_yaml = """
        - - method: %s
            url: %s
            reply: %s
        """ % (method, url, reply)
    script = canned_http.parse_yaml_from_string(raw_yaml)
    self.assertEqual(1, len(script._connections))
    connection = script._connections[0]
    self.assertEqual(1, len(connection._exchanges))
    exchange = connection._exchanges[0]
    self._assert_exchange(exchange, method.upper(), url, reply=reply)

  def test_empty_script(self):
    raw_yaml = """
        """
    script = canned_http.parse_yaml_from_string(raw_yaml)
    self.assertEqual(0, len(script._connections))

  def test_valid_script(self):
    raw_yaml = """
        - - method: GET
            url: /foo1.html
            reply: reply1
          - method: POST
            body: body1
            url: /foo2.html
        - - method: DELETE
            url: /foo3.html
            reply: reply3
            delay: 1000
        """
    script = canned_http.parse_yaml_from_string(raw_yaml)
    self.assertEqual(2, len(script._connections))
    # Verify the two exchanges of the first connection.
    connection = script._connections[0]
    self.assertEqual(2, len(connection._exchanges))
    # Verify the one exchange of the second connection.
    connection = script._connections[1]
    self.assertEqual(1, len(connection._exchanges))
    exchange = connection._exchanges[0]


class TestDirector(unittest.TestCase):
  def test_empty_script(self):
    script = canned_http.Script()
    director = canned_http.Director(script)
    self.assertTrue(director.is_done())

  def test_invalid_events(self):
    # Raise exception if connection opened after the script ended.
    script = canned_http.Script()
    director = canned_http.Director(script)
    with self.assertRaises(canned_http.DirectorException):
      director.connection_opened()
    # Raise exception if got request instead of closing the connection.
    raw_yaml = """
        - - method: GET
            url: /foo1.html
            reply: reply1
        """
    script = canned_http.parse_yaml_from_string(raw_yaml)
    director = canned_http.Director(script)
    director.connection_opened()
    director.got_request('GET', '/foo1.html')
    with self.assertRaises(canned_http.DirectorException):
      director.got_request('GET', '/foo2.html')
    # Raise exception if closed connection instead of getting a request.
    raw_yaml = """
        - - method: GET
            url: /foo1.html
            reply: reply1
          - method: GET
            url: /foo2.html
            reply: reply2
        """
    script = canned_http.parse_yaml_from_string(raw_yaml)
    director = canned_http.Director(script)
    director.connection_opened()
    director.got_request('GET', '/foo1.html')
    with self.assertRaises(canned_http.DirectorException):
      director.connection_closed()

if __name__ == '__main__':
  unittest.main()

