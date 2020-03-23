"""A python wrapper for wrk."""
import socket
import sys
import asyncio
from asyncio.subprocess import PIPE, STDOUT
from http.server import BaseHTTPRequestHandler, HTTPServer

import yaml
import psutil
import uvloop
from yaml.scanner import ScannerError
from pyecharts import Page
from pyecharts import Bar
from pyecharts import Line


PORT = 8899
benchmarks = {}
cpu_usage = {}


async def run_wrk(url, conn, option):
    print('run at {} with {} connections'.format(url, conn))
    rps = 0.0
    p = await asyncio.create_subprocess_exec(
        'wrk', '-t', str(option['threads']), '-c', conn, '-d', str(option['duration']), '-s', 'pipeline.lua',
        url, stdout=PIPE, stderr=STDOUT)

    stdout, stderr = await p.communicate()
    stdout = stdout.decode('utf-8')
    #print('stdout: {}, stderr: {}'.format(stdout, stderr))
    if stdout:
        for line in stdout.split('\n'):
            if line.startswith('Requests/sec:'):
                rps = float(line.split()[-1])

    if p.returncode != 0:
        print('run wrk error: {} '.format(stdout))

    benchmarks[conn][url] = rps
    return rps


async def cpu_percent(interval=None, *args, **kwargs):
    if interval is not None and interval > 0.0:
        psutil.cpu_percent(*args, **kwargs)
        await asyncio.sleep(interval)
    cpu = psutil.cpu_percent(*args, **kwargs)
    return cpu


async def monitor(url, conn, duration=10):
    for _ in range(duration):
        cpu = await cpu_percent(1)
        cpu_usage[conn][url].append(cpu)


class RequestHandler(BaseHTTPRequestHandler):
    def get(self):
        # Send response status code
        self.send_response(200)

        self.send_header('Content-type','text/html')
        self.end_headers()

        with open('render.html') as f:
            message = f.readlines()
        self.wfile.write(bytes(message, "utf8"))
        return


class MyServer(BaseHTTPRequestHandler):

    def do_GET(self):
        try:
            with open('./render.html', 'rb') as f:
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(f.read())
            return
        except IOError:
            self.send_error(404, 'File Not Found: %s' % self.path)


def get_ip():
    try:
        host_name = socket.gethostname()
        host_ip = socket.gethostbyname(host_name)
        return host_ip
    except:
        return 'localhost'


async def run_benchmark(option):
    urls = option['urls']
    # convert to string in order to used in dict
    conns = [str(conn) for conn in option['connections']]

    for conn in conns:
        benchmarks[conn] = {}
        cpu_usage[conn] = {}
        for url in urls:
            benchmarks[conn][url] = []
            cpu_usage[conn][url] = []
            benchmark_task = asyncio.ensure_future(
                run_wrk(url, conn, option))
            monitor_task = asyncio.ensure_future(
                monitor(url, conn, option['duration']))
            # TODO: 这里需要修改为如果主任务异常退出，则monitor任务也停止
            done, pending = await asyncio.wait(
                [benchmark_task, monitor_task],
                return_when=asyncio.ALL_COMPLETED,
            )
    for task in pending:
        task.cancel()

    print('Result: {} \n{}'.format(benchmarks, cpu_usage))
    page = Page()

    tps_bar = Bar("测试结果", "")
    cpu_line = Line("CPU占用率")

    v = {}
    for conn in conns:
        v[conn] = []
        for url in urls:
            v[conn].append(benchmarks[conn][url])

    for conn in conns:
        tps_bar.add(conn+'连接', urls, v[conn])
        for url in urls:
            cpu_line.add(url+' ' + conn+'连接', [i for i in range(option['duration'])], cpu_usage[conn][url], yaxis_max=100, yaxis_formatter=" %")

    page.add(tps_bar)
    page.add(cpu_line)
    page.render()

    print('Result on: http://{}:{}'.format(get_ip(), PORT))
    server = HTTPServer(('0.0.0.0', PORT), MyServer)
    server.serve_forever()
    server.server_close()


def main():
    loop = uvloop.new_event_loop()
    with open('site.yml', 'r') as f:
        try:
            option = yaml.load(f, Loader=yaml.FullLoader)
            if not option:
                print('read file error!')
                return 1
            print(option)
        except (KeyError, ScannerError) as e:
            print(e.note)
            print(e.problem)
            print(e.problem_mark)
            return 1
    loop.run_until_complete(run_benchmark(option))


if __name__ == '__main__':
    main()
