Canned HTTP
===========

A web server that accepts HTTP requests from a client, verifies that each
request contains some expected values, and returns canned responses for the
requests. The expected values in the requests and the canned responses are
specified by a script that is provided when the web server is run.

Script values
-------------

For requests, the script specifies the following parameters:

* `method` (required): The HTTP method used, such as `GET` or `POST`.
* `url` (required): The URL path requested.
* `headers` (optional): A map of expected HTTP headers. If provided, the headers
  of a request must be a superset of these headers.
* `body` (optional): The expected body of the request, such as the data
  submitted in a `POST` request.
* `body_filename` (optional): The filename whose contents should be expected as
  the body of the request.
* `body_type`: (optional): If present, the received body and the expected body
  will be converted to the given type before returning. Currently the only
  valid value is `JSON`.

If the request is expected to contain a body, then exactly one of `body` and
`body_filename` must be set. Setting both is invalid.

For responses, the script specifies the following parameters:

* `status_code` (required): The HTTP status code to return, such as `200` or `404`.
* `content_type` (required): The value of the `Content-Type` header to return.
* `headers` (optional): A map of HTTP header names and values to return in the
  response.
* `delay` (optional): The number of seconds to wait before sending the response,
  which is useful for simulating long-polling by the server.
* `body` (optional): The body of the response, such as the HTML to render in the
  browser in response to a `GET` request.
* `body_filename` (optional): The filename whose contents should be used as the
  body of the response.

A response can be omitted altogether, which is useful for simulating
long-polling where the client must close the connection. If a response is
present, then exactly one of `body` and `body_filename` must be set. Setting both
or neither is invalid.

A request and the optional response is called an exchange. The persistent
connections feature of HTTP 1.1 allows multiple exchanges over a single TCP/IP
connection between the client and the server, provided that every exchange
except the last includes a response. An array of exchanges represents all the
exchanges across a single connection. The script is simply an array of such
arrays, so that it specifies the number of expected connections, and the order
of exchanges for each connection.

Example script
--------------

Below I define a script that waits for a client to connect and `GET` the URL
`/page1.html`. The server waits five seconds, and then responds with a
`200` (OK) status code and a simple HTML document that references no
additional resources. Browsers then, using the same HTTP connection, request
the `favicon.ico` file. The server returns the contents of the `favicon.ico`
file in the same directory as the script. After receiving this file, browsers
close the connection, at which point the script has run to completion.

Here is the script in YAML format. The dash with no indent specifies an expected
connection, while the indented dashes specify expected exchanges on a connection.

    - - request:
          method: GET
          url: /page1.html
        response:
          status_code: 200
          content_type: text/html; charset=utf-8
          delay: 5
          body: <html><body>It took awhile, but the answer is<h2>42</h2></body></html>
      - request:
          method: GET
          url: /favicon.ico
        response:
          status_code: 200
          content_type: image/x-icon
          body_filename: favicon.ico

Here is the script in JSON format. The outer-most array specifies the
expected connections, while nested arrays specify expected exchanges on
a connection.

    [ [ { "request": {
            "method": "GET",
            "url": "/page1.html" },
          "response": {
            "status_code": 200,
            "content_type": "text/html; charset=utf-8",
            "delay": 5,
            "body": "<html><body>It took awhile, but the answer is<h2>42</h2></body></html>" }
        },
        { "request": {
            "method": "GET",
            "url": "/favicon.ico" },
         "response": {
            "status_code": 200,
            "content_type": "image/x-icon",
            "body_filename": "favicon.ico" }
        }
      ]
    ]

Running a script
----------------

The following command line arguments are accepted:

* `port` (optional): The port to run the web server on. The default is 8080.
* `json_filename` (optional): The filename containing a script in JSON format.
* `yaml_filename` (optional): The filename containing a script in YAML format.

Exactly one of `json_filename` and `yaml_filename` must be set. Setting both
or neither is invalid.

To run a script in YAML format or to run the unit tests successfully,
[LibYaml](http://pyyaml.org/wiki/LibYAML) must be installed. If missing, simply
define scripts in JSON format.

Reading the output
------------------

The script shown above is found under `/examples/ex1.yaml` and `/examples/ex1.json`.
If the user tries to access `/page2.html` instead of `/page1.html` in a browser,
the following output is shown:

    mgp:~/canned-http $ python canned_http.py --yaml_filename=examples/ex1.yaml 
    ERROR:  Expected 'url' value '/page1.html', received '/page2.html' for connection 1, exchange 1
    mgp:~/canned-http $

The script expected the client to request `page1.html` for the first exchange
of the first connection, but instead the client requested `page2.html`.