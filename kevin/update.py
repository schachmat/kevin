""" The various job update objects """

import json
import time as clock
from abc import ABCMeta

ALLOWED_BUILD_STATES = {"pending", "success", "failure", "error"}
FINISH_STATES = {"success", "failure", "error"}
SUCCESS_STATES = {"success"}
ERROR_STATES = {"error"}

UPDATE_CLASSES = {}


class UpdateMeta(ABCMeta):
    """ Update metaclass. Adds the classes to UPDATE_CLASSES. """
    def __init__(cls, name, bases, classdict):
        super().__init__(name, bases, classdict)
        UPDATE_CLASSES[name] = cls


class Update(metaclass=UpdateMeta):
    """
    Abstract base class for all JSON-serializable Update objects.
    __init__() should simply set the update's member variables.
    """

    # which of the member variables should not be sent via json?
    BLACKLIST = set()

    def dump(self):
        """
        Dump members as a dict, except those in BLACKLIST.
        The dict shall be suitable for feeding back into __init__ as kwargs.
        """
        return {
            k: v for k, v in self.__dict__.items()
            if k not in self.BLACKLIST
        }

    def json(self):
        """
        Returns a JSON-serialized string of self (via self.dump()).
        This string will be broadcast via WebSocket and saved to disk.
        """
        result = self.dump()
        result['class'] = type(self).__name__
        return json.dumps(result)

    def __repr__(self):
        return self.json()

    @staticmethod
    def construct(jsonmsg):
        """
        Constructs an Update object from a JSON-serialized string.
        The 'class' member is used to determine the subclass that shall be
        built, the rest is passed on to the constructor as kwargs.
        """
        data = json.loads(jsonmsg)
        classname = data['class']
        del data['class']
        return UPDATE_CLASSES[classname](**data)


class GeneratedUpdate(Update):
    """
    An update that is created by processing other updates,
    therefore should never be stored.

    When the other updates are replayed, this update is triggered again.
    This is why it must not be stored.
    """
    pass


class JobUpdate(Update):
    """
    An update that is assigned to a job.
    """

    def apply_to(self, job):
        """
        Update-specific code to modify the thing object on job.update().
        No-op by default.
        Raise to report errors.
        """
        pass


class BuildUpdate(Update):
    """
    An update that is assigned to a build.
    """
    pass


class JobCreated(GeneratedUpdate, JobUpdate):
    """
    Update that notifies the creation of a job.
    """
    def __init__(self, build_id, job_name):
        self.build_id = build_id
        self.job_name = job_name


class JobAbort(JobUpdate):
    """
    Update that notifies a job it should abort now.
    """
    def __init__(self, job_name):
        self.job_name = job_name


class BuildSource(Update):
    """
    A new source for the build.
    A source is a place from which the request to build this SHA1 has
    originated.
    A build must have at least one of these updates in order to be
    buildable (we must know a clone_url).
    """
    def __init__(self, clone_url, repo_url, author, branch, comment):
        self.clone_url = clone_url
        self.repo_url = repo_url
        self.author = author
        self.branch = branch
        self.comment = comment


class State(Update):
    """ Overall state change """
    def __init__(self, state, text, time=None):
        if state not in ALLOWED_BUILD_STATES:
            raise ValueError("Illegal state: " + repr(state))
        if not text.isprintable():
            raise ValueError("State.text not printable: " + repr(text))
        if time is None:
            time = clock.time()
        elif not (isinstance(time, int) or isinstance(time, float)):
            raise TypeError("State.time not a number, is %s: %s" % (
                type(time), repr(time)
            ))

        self.state = state
        self.text = text
        self.time = time

    def is_succeeded(self):
        """ return if the build succeeded """
        return self.state in SUCCESS_STATES

    def is_finished(self):
        """ return if the build is no longer running """
        return self.state in FINISH_STATES

    def is_errored(self):
        """ return if the build is no longer running """
        return self.state in ERROR_STATES


class BuildState(GeneratedUpdate, State):
    """ Build specific state changes """

    def __init__(self, state, text, time=None):
        State.__init__(self, state, text, time)


class JobState(JobUpdate, State):
    """ Job specific state changes """

    def __init__(self, job_name, state, text, time=None):
        State.__init__(self, state, text, time)
        self.job_name = job_name


class StepState(JobUpdate):
    """ Step build state change """

    # don't dump these
    BLACKLIST = {"step_number"}

    def __init__(self, job_name, step_name, state, text, time=None,
                 step_number=None):
        if not step_name.isidentifier():
            raise ValueError("StepState.step_name invalid: %r" % (step_name))
        if time is None:
            time = clock.time()

        self.job_name = job_name
        self.step_name = step_name
        self.step_number = step_number
        self.state = state
        self.text = text
        self.time = time

    def apply_to(self, job):
        job.step_update(self)


class OutputItem(JobUpdate):
    """ Job has produced an output item """
    def __init__(self, name, isdir, size=0):
        if not name:
            raise ValueError("output item name must not be empty")
        if not name[0].isalpha():
            raise ValueError("output item name must start with a letter")
        if not name.isprintable() or (set("/\\'\"") & set(name)):
            raise ValueError("output item name contains illegal characters")

        self.name = name
        self.isdir = isdir
        self.size = size

    def validate_path(self, path):
        """
        Raises an exception if path is not a valid subdir of this.
        """
        components = path.split('\n')
        if components[0] != self.name:
            raise ValueError("not a subdir of " + self.name + ": " + path)

        for component in components[1:]:
            if not component.isprintable():
                raise ValueError("non-printable character(s): " + repr(path))
            if component in {'.', '..'}:
                raise ValueError("invalid component name(s): " + path)

    def apply_to(self, job):
        job.output_items.add(self)
        job.remaining_output_size -= self.size


class StdOut(JobUpdate):
    """ Process has produced output on the TTY """
    def __init__(self, data):
        if not isinstance(data, str):
            raise TypeError("StdOut.data not str: %r" % (data,))

        self.data = data


class Enqueued(GeneratedUpdate):
    """ The build was enqueued and jobs can be run. """

    BLACKLIST = {"queue"}

    def __init__(self, queue=None):
        self.queue = queue
