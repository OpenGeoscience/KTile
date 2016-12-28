from __future__ import print_function
from tempfile import mkstemp
import os
import inspect
import socket
from subprocess import Popen, PIPE, STDOUT
import shlex
import sys
from time import sleep
from threading  import Thread
try:
    from Queue import Queue, Empty
except ImportError:
    from queue import Queue, Empty  # python 3.x


from ModestMaps.Core import Coordinate
from TileStache import getTile, parseConfig
from TileStache.Core import KnownUnknown

def request(config_content, layer_name, format, row, column, zoom):
    '''
    Helper method to write config_file to disk and do
    request
    '''
    if sys.version_info.major == 2:
        is_string = isinstance(config_content, basestring)
    else:
        is_string = type(config_content) in (str, bytes)

    if is_string:
        absolute_file_name = create_temp_file(config_content)
        config = parseConfig(absolute_file_name)

    else:
        config = parseConfig(config_content)

    layer = config.layers[layer_name]
    coord = Coordinate(int(row), int(column), int(zoom))
    mime_type, tile_content = getTile(layer, coord, format)

    if is_string:
        os.remove(absolute_file_name)

    return mime_type, tile_content

def create_temp_file(buffer):
    '''
    Helper method to create temp file on disk. Caller is responsible
    for deleting file once done
    '''
    fd, absolute_file_name = mkstemp(text=True)
    file = os.fdopen(fd, 'w')
    file.write(buffer)
    file.close()
    return absolute_file_name

def create_dummy_server(file_with_content, mimetype):
    '''
    Helper method that creates a dummy server that always
    returns the contents of the file specified with the
    mimetype specified
    '''

    current_script_dir = os.path.dirname(os.path.abspath(__file__))

    #start new process using our dummy-response-server.py script
    dummy_server_file = os.path.join(current_script_dir, 'servers', 'dummy-response-server.py')
    port = find_open_port()
    cmd = 'python %s %s "%s" "%s" ' % (dummy_server_file, str(port), file_with_content, mimetype)

    ON_POSIX = 'posix' in sys.builtin_module_names

    p = Popen(shlex.split(cmd), stdout=PIPE, stderr=STDOUT, bufsize=1, close_fds=ON_POSIX)

    # Read the stdout and look for Werkzeug's "Running on" string to indicate the server is ready for action.
    # Otherwise, keep reading. We are using a Queue and a Thread to create a non-blocking read of the other
    # process as described in http://stackoverflow.com/questions/375427/non-blocking-read-on-a-subprocess-pipe-in-python
    # I wanted to use communicate() originally, but it was causing a blocking read and this way will also
    # work on Windows

    q = Queue()
    t = Thread(target=enqueue_output, args=(p.stdout, q))
    t.daemon = True # thread dies with the program
    t.start()

    server_output = b''

    # read line and enter busy loop until the server says it is ok
    while True:
        retcode = p.poll()
        if retcode is not None:
            # process has terminated abruptly
            raise Exception('The test dummy server failed to run. code:[%s] cmd:[%s]'%(str(retcode),cmd))

        try:
            line = q.get_nowait()
        except Empty:
            sleep(0.01)
            continue
        else: # got line
            server_output += line
            if b"Running on http://" in server_output:
                break; #server is running, get out of here
            else:
                continue

    return p, port


def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()

def find_open_port():
    '''
    Ask the OS for an open port
    '''
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("",0))
    port = s.getsockname()[1]
    s.close()
    return port