"""
Simulates the github pull request api.
"""

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import pathlib
import requests
import traceback

from tornado import web, gen
from tornado.platform.asyncio import AsyncIOMainLoop

from . import util
from . import service
from ..service.github import GitHubHook


class GitHub(service.Service):
    """
    The simlated github service. Uses config from kevin.
    """

    def __init__(self, args):
        super().__init__(args)

        # url where to push updates to.
        self.status_handler = "/%s" % args.statuspath
        self.repo_handler = "/repo"

    @classmethod
    def argparser(cls, subparsers):
        cli = subparsers.add_parser("github", help="simulate github")
        cli.add_argument("--statuspath", default="statusupdate",
                         help="url component where status updates are sent")
        cli.set_defaults(service=cls)

    def run(self):
        """
        creates the interaction server
        """
        self.loop = asyncio.get_event_loop()
        AsyncIOMainLoop().install()

        print("Creating simulated server...")

        # create server
        handlers = [
            (self.status_handler, UpdateHandler, {"config": self.cfg,
                                                  "project": self.project}),
        ]

        # add http server to serve a local repo to qemu
        if self.local_repo and pathlib.Path(self.repo).is_dir():
            print("Serving '%s' on 'http://%s:%d%s/'" % (
                self.repo,
                self.listen,
                self.port,
                self.repo_handler
            ))

            handlers.append(
                (r"%s/(.*)" % self.repo_handler,
                 web.StaticFileHandler, dict(path=self.repo))
            )
            self.repo_vm = "http://%s:%d%s" % (self.local_repo_address,
                                               self.port,
                                               self.repo_handler)

        self.app = web.Application(handlers)
        print("listening on port %s:%d" % (self.listen, self.port))
        self.app.listen(self.port, address=str(self.listen))

        # submit web hook
        webhook = self.loop.create_task(self.submit_web_hook())

        try:
            self.loop.run_forever()
        except KeyboardInterrupt:
            print("exiting...")

        if not webhook.done():
            webhook.cancel()

        asyncio.wait(webhook, timeout=10)
        self.loop.close()

    @asyncio.coroutine
    def submit_web_hook(self):
        """
        create the webhook to kevin to trigger it.
        """

        if isinstance(self.listen, ipaddress.IPv6Address):
            ip = "[%s]" % (self.listen)
        else:
            ip = str(self.listen)

        status_url = "http://%s:%d%s" % (ip, self.port, self.status_handler)
        head_commit = yield from util.get_hash(self.repo)

        if self.repo_vm:
            yield from util.update_server_info(self.repo)

        repo = self.repo_vm or self.repo
        project = self.cfg.projects[self.project]

        # chose first github trigger in the project config
        trigger = None
        for trigger_test in project.triggers:
            if isinstance(trigger_test, GitHubHook):
                trigger = trigger_test
                break

        if trigger is None:
            raise Exception("couldn't find github trigger in project.")

        # select first allowed repo as virtual "origin"
        reponame = trigger.repos[0]
        hooksecret = trigger.hooksecret

        pull_req = {
            "action": "synchronize",
            "sender": {"login": "rolf"},
            "pull_request": {
                "head": {
                    "repo": {
                        "clone_url": repo,
                        "html_url": repo,
                    },
                    "sha": head_commit,
                    "label": "lol:epic_update",
                },
                "statuses_url": status_url,
            },
            "repository": {
                "full_name": reponame,
            },
        }

        payload = json.dumps(pull_req).encode()

        # calculate hmac
        signature = 'sha1=' + hmac.new(hooksecret,
                                       payload, hashlib.sha1).hexdigest()
        headers = {"X-Hub-Signature": signature,
                   "X-GitHub-Event": "pull_request"}

        def submit_post():
            try:
                return requests.post(
                    url=self.cfg.dyn_url + "hook-github",
                    data=payload,
                    headers=headers,
                    timeout=5.0,
                )
            except requests.exceptions.RequestException as exc:
                print("failed delivering webhook: %s" % (exc))
                return "failed."

        post = self.loop.run_in_executor(None, submit_post)
        hook_answer = yield from post

        print("hook delivery: %s" % hook_answer)


class UpdateHandler(web.RequestHandler):
    """
    Handles a POST from kevin.
    """

    def initialize(self, config, project):
        self.cfg = config
        self.project = project

    def get(self):
        self.write(b"Expected a JSON-formatted POST request.\n")
        self.set_status(400)
        self.finish()

    def post(self):
        print("\x1b[34mUpdate from %s:\x1b[m" % self.request.remote_ip,
              end=" ")
        blob = self.request.body
        try:
            auth_header = self.request.headers.get('Authorization').encode()
            if auth_header is None:
                self.set_status(401, "no authorization given!")
                self.finish()
                return

            if not auth_header.startswith(b"Basic "):
                raise ValueError("wrong auth type")

            auth = base64.decodebytes(auth_header[6:]).decode().split(":", 2)

            authtok = self.cfg.projects[self.project].actions[0].authtoken
            if tuple(auth) != authtok:
                print("wrong auth tried: %s" % (auth,))
                print("expected: %s" % (authtok,))
                raise ValueError("wrong authentication")

            self.handle_update(blob)

        except (ValueError, KeyError) as exc:
            print("bad request: " + repr(exc))
            traceback.print_exc()

            self.write(repr(exc).encode())
            self.set_status(400, "Bad request")

        except (BaseException) as exc:
            print("\x1b[31;1mexception in post hook\x1b[m")
            traceback.print_exc()

            self.set_status(500, "Internal error")
            self.set_header("Status", "internal fail")
        else:
            self.write(b"OK")
            self.set_header("status", "ok")
        self.finish()

    def handle_update(self, data):
        """
        Process a received update and present it in a shiny way graphically.
        Ensures maximum readability by dynamically formatting the text in
        a responsive way, that is even available on mobile devices.

        This output is plattform-independent, it may even work on windows.
        TODO: write testcases
        """
        print("%s" % data)
