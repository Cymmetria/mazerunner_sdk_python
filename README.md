# MazeRunner Python SDK


This library implements a convenient client for MazeRunner API for python.

Using this library, you'll be able to easily configure and manipulate 

the key features of MazeRunner, such as creation of a deception campaign, turning 

decoys on or off, deployment on remote endpoints, and inspect alerts with their 

attached evidence.

For a quick start, it's recommended to perform the easy steps in the installation section, and

continue to trying some of the usage examples in the mazerunner/samples folder.

###Run tests:
`py.test -vvv --json_credentials=my_keys.json --lab_dependent --cov=mazerunner.api_client --cov-report html`

Structure of the json_credentials file:
~~~~
{
    "ip_address": "mazerunner.host.or.ip",
    "id": "mazerunner_api_key",
    "secret": "mazerunner_api_secret",
    "mazerunner_certificate_path": "MazeRunner.crt",
    "endpoint_ip": "endpoint.host.or.ip",
    "endpoint_username": "ep_username",
    "endpoint_password": "ep_password"
}
~~~~

###Generate documentation files:
~~~~
make dev-env
make docs
~~~~

###See documentation at [https://community.cymmetria.com/api](https://community.cymmetria.com/api)
