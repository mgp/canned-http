import unittest

import canned_http

class TestParseYaml(unittest.TestCase):
  def _assert_request(self, exchange, method, url, headers={}, body=None):
    request = exchange._request
    self.assertEqual(method, request._method)
    self.assertEqual(url, request._url)
    self.assertDictEqual(headers, request._headers)
    self.assertEqual(body, request._body)

  def _assert_no_response(self, exchange):
    self.assertIsNone(exchange._response)

  def _assert_response(self, exchange, status_code, content_type, headers={}, delay=0,
      body=None, body_filename=None):
    response = exchange._response
    self.assertEqual(status_code, response._status_code)
    self.assertEqual(content_type, response._content_type)
    self.assertDictEqual(headers, response._headers)
    self.assertEqual(delay, response._delay)
    self.assertEqual(body, response._body)
    self.assertEqual(body_filename, response._body_filename)

  def test_invalid_script(self):
    # Raise exception if method is missing in request.
    raw_yaml = """
        - - request:
              url: /foo.html
            response:
              status_code: 200
              content_type: html
              body: <html><body></body></html>
        """
    with self.assertRaises(canned_http.ScriptParseError):
      canned_http.script_from_yaml_string(raw_yaml)
    # Raise exception if method is invalid in request.
    raw_yaml = """
        - - request:
              method: PONY
              url: /foo.html
            response:
              status_code: 200
              content_type: html
              body: <html><body></body></html>
        """
    with self.assertRaises(canned_http.ScriptParseError):
      canned_http.script_from_yaml_string(raw_yaml)
    # Raise exception if url is missing in request.
    raw_yaml = """
        - - request:
              method: GET
            response:
              status_code: 200
              content_type: html
              body: <html><body></body></html>
        """
    with self.assertRaises(canned_http.ScriptParseError):
      canned_http.script_from_yaml_string(raw_yaml)
    # Raise exception if status code is missing in response.
    raw_yaml = """
        - - request:
              method: GET
              url: /foo.html
            response:
              content_type: html
              body: <html><body></body></html>
        """
    with self.assertRaises(canned_http.ScriptParseError):
      canned_http.script_from_yaml_string(raw_yaml)
    # Raise exception if content type is missing in response.
    raw_yaml = """
        - - request:
              method: GET
              url: /foo.html
            response:
              status_code: 200
              body: <html><body></body></html>
        """
    with self.assertRaises(canned_http.ScriptParseError):
      canned_http.script_from_yaml_string(raw_yaml)
    # Raise exception if both body and filename are present in response.
    raw_yaml = """
        - - request:
              method: GET
              url: /foo.html
            response:
              status_code: 200
              content_type: html
              body: <html><body></body></html>
              body_filename: favicon.ico
        """
    with self.assertRaises(canned_http.ScriptParseError):
      canned_http.script_from_yaml_string(raw_yaml)
    # Raise exception if reply is missing for exchange that is not last.
    raw_yaml = """
        - - request:
              method: GET
              url: /foo1.html
          - request:
              method: GET
              url: /foo2.html
            response:
              status_code: 200
              content_type: html
              body: <html><body></body></html>
        """
    with self.assertRaises(canned_http.ScriptParseError):
      canned_http.script_from_yaml_string(raw_yaml)

  def test_method_capitalization(self):
    # Capitalization of method should not matter.
    method = 'PuT'
    url = '/foo.html'
    status_code = 200
    content_type = 'html'
    response_body = '<html><body></body></html>'
    raw_yaml = """
        - - request:
              method: %s
              url: %s
            response:
              status_code: %s
              content_type: %s
              body: %s
        """ % (method, url, status_code, content_type, response_body)
    script = canned_http.script_from_yaml_string(raw_yaml)
    self.assertEqual(1, len(script._connections))
    connection = script._connections[0]
    self.assertEqual(1, len(connection._exchanges))
    exchange = connection._exchanges[0]
    self._assert_request(exchange, method, url)
    self._assert_response(exchange, status_code, content_type, body=response_body)

  def test_empty_script(self):
    raw_yaml = """
        """
    script = canned_http.script_from_yaml_string(raw_yaml)
    self.assertEqual(0, len(script._connections))

  def test_valid_script(self):
    raw_yaml = """
        - - request:
              method: GET
              url: /foo1.html
            response:
              status_code: 200
              content_type: html
              body: response_body1 
          - request:
              method: POST
              url: /foo2.html
              body: request_body2
        - - request:
              method: DELETE
              url: /foo3.html
            response:
              status_code: 200
              content_type: html
              delay: 1000
              body_filename: response_body_filename3
        """
    script = canned_http.script_from_yaml_string(raw_yaml)
    self.assertEqual(2, len(script._connections))

    # Verify the two exchanges of the first connection.
    connection = script._connections[0]
    self.assertEqual(2, len(connection._exchanges))
    exchange = connection._exchanges[0]
    self._assert_request(exchange, 'GET', '/foo1.html')
    self._assert_response(exchange, 200, 'html', body='response_body1')
    exchange = connection._exchanges[1]
    self._assert_request(exchange, 'POST', '/foo2.html', body='request_body2')
    self._assert_no_response(exchange)

    # Verify the one exchange of the second connection.
    connection = script._connections[1]
    self.assertEqual(1, len(connection._exchanges))
    exchange = connection._exchanges[0]
    self._assert_request(exchange, 'DELETE', '/foo3.html')
    self._assert_response(exchange, 200, 'html', delay=1000,
        body_filename='response_body_filename3')


class TestDirector(unittest.TestCase):
  def test_empty_script(self):
    script = canned_http.Script()
    director = canned_http.Director(script)
    self.assertTrue(director.is_done())

  def test_invalid_events(self):
    # Raise an exception if connection opened after the script ended.
    script = canned_http.Script()
    director = canned_http.Director(script)
    with self.assertRaises(canned_http.DirectorError):
      director.connection_opened()
    # Raise an exception if got request instead of closing the connection.
    raw_yaml = """
        - - request:
              method: GET
              url: /foo1.html
            response:
              status_code: 200
              content_type: html
              body: body1
        """
    script = canned_http.script_from_yaml_string(raw_yaml)
    director = canned_http.Director(script)
    director.connection_opened()
    director.got_request('GET', '/foo1.html')
    with self.assertRaises(canned_http.DirectorError):
      director.got_request('GET', '/foo2.html')
    # Raise an exception if closed connection instead of getting a request.
    raw_yaml = """
        - - request:
              method: GET
              url: /foo1.html
            response:
              status_code: 200
              content_type: html
              body: body1
          - request:
              method: GET
              url: /foo2.html
            response:
              status_code: 200
              content_type: html
              body: body2
        """
    script = canned_http.script_from_yaml_string(raw_yaml)
    director = canned_http.Director(script)
    director.connection_opened()
    director.got_request('GET', '/foo1.html')
    with self.assertRaises(canned_http.DirectorError):
      director.connection_closed()

  def test_invalid_exchanges(self):
    raw_yaml = """
        - - request:
              method: GET
              url: /foo1.html
              headers:
                header_name1: header_value1
            response:
              status_code: 200
              content_type: html
              body: body1 
        """
    script = canned_http.script_from_yaml_string(raw_yaml)
    # Raise an exception if the wrong method is used.
    director = canned_http.Director(script)
    director.connection_opened()
    with self.assertRaises(canned_http.DirectorError):
      director.got_request('PUT', '/foo1.html', {'header_name1': 'header_value1'})
    # Raise an exception if the wrong URL is requested.
    director = canned_http.Director(script)
    director.connection_opened()
    with self.assertRaises(canned_http.DirectorError):
      director.got_request('GET', '/foo2.html', {'header_name1': 'header_value1'})
    # Raise an exception if a body is provided when it should not.
    director = canned_http.Director(script)
    director.connection_opened()
    with self.assertRaises(canned_http.DirectorError):
      director.got_request(
          'GET', '/foo1.html', {'header_name1': 'header_value1'}, 'body')
    # Raise an exception if a wrong header value is provided.
    director = canned_http.Director(script)
    director.connection_opened()
    with self.assertRaises(canned_http.DirectorError):
      director.got_request(
          'GET', '/foo1.html', {'header_name1': 'header_value2'}, 'body')
    # Raise an exception if a wrong header name is provided.
    director = canned_http.Director(script)
    director.connection_opened()
    with self.assertRaises(canned_http.DirectorError):
      director.got_request(
          'GET', '/foo1.html', {'header_name2': 'header_value1'}, 'body')
    # Raise an exception if no body is provided when it should be.
    raw_yaml = """
        - - request:
              method: GET
              url: /foo1.html
              body: body1
            response:
              status_code: 200
              content_type: html
              body: body2 
        """
    script = canned_http.script_from_yaml_string(raw_yaml)
    director = canned_http.Director(script)
    director.connection_opened()
    with self.assertRaises(canned_http.DirectorError):
      director.got_request('GET', '/foo1.html')

  def test_request_headers(self):
    raw_yaml = """
        - - request:
              method: GET
              url: /foo1.html
              headers:
                header_name1: header_value1
            response:
              status_code: 200
              content_type: html
              body: body1 
        """
    script = canned_http.script_from_yaml_string(raw_yaml)
    # Capitalization of header values should matter.
    director = canned_http.Director(script)
    director.connection_opened()
    with self.assertRaises(canned_http.DirectorError):
      director.got_request('GET', '/foo1.html', {'header_name1': 'HEADER_VALUE1'})
    # Extra header names should not matter.
    director = canned_http.Director(script)
    director.connection_opened()
    director.got_request('GET', '/foo1.html',
        {'header_name1': 'header_value1', 'header_name2': 'header_value2'})
    director.connection_closed()

  def _assert_response(self, response, status_code, content_type,
      delay=0, headers={}, body=None, body_filename=None):
    self.assertEqual(status_code, response._status_code)
    self.assertEqual(content_type, response._content_type)
    self.assertEqual(delay, response._delay)
    self.assertDictEqual(headers, response._headers)
    self.assertEqual(body, response._body)
    self.assertEqual(body_filename, response._body_filename)

  def test_valid_script(self):
    raw_yaml = """
        - - request:
              method: GET
              url: /foo1.html
            response:
              status_code: 200
              content_type: html
              body: body1
              delay: 50
          - request:
              method: POST
              url: /foo2.html
              body: body2
        - - request:
              method: DELETE
              url: /foo3.html
              body: body3
            response:
              status_code: 200
              content_type: html
              body: body3
        """
    script = canned_http.script_from_yaml_string(raw_yaml)
    director = canned_http.Director(script)

    # Verify the two exchanges of the first connection.
    director.connection_opened()
    response = director.got_request('GET', '/foo1.html')
    self._assert_response(response, 200, 'html', delay=50, body='body1')
    response = director.got_request('POST', '/foo2.html', body='body2')
    self.assertIsNone(response)
    director.connection_closed()

    # Verify the one exchange of the second connection.
    director.connection_opened()
    response = director.got_request('DELETE', '/foo3.html', body='body3')
    self._assert_response(response, 200, 'html', body='body3')
    director.connection_closed()

if __name__ == '__main__':
  unittest.main()

