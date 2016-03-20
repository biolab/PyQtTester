#!/usr/bin/env python3

import sys; REAL_EXIT = sys.exit
import os
import re
import signal
import subprocess
from functools import reduce, wraps
from collections import namedtuple
from itertools import chain, islice, count, repeat
from importlib import import_module

try: import cPickle as pickle
except ImportError: import pickle


try: from functools import lru_cache
except ImportError:  # Py2
    def lru_cache(_):
        def decorator(func):
            cache = {}
            @wraps(func)
            def f(*args, **kwargs):
                key = (args, tuple(kwargs.items()))
                if key not in cache:
                    cache[key] = func(*args, **kwargs)
                return cache[key]
            return f
        return decorator


__version__ = '0.1.0'

SCENARIO_FORMAT_VERSION = 1


def deepgetattr(obj, attr):
    """Recurses through an attribute chain to get the ultimate value."""
    return reduce(getattr, attr.split('.'), obj)


def nth(n, iterable, default=None):
    """Return the n-th item of iterable"""
    return next(islice(iterable, n, None), default)


def typed_nth(n, target_type, iterable, default=None):
    """Return the n-th item of type from iterable"""
    return nth(n, (i for i in iterable if type(i) == target_type), default)


## This shell script is run if program is run with --x11 option
SHELL_SCRIPT = r'''

# set -x  # Enable debugging
set -e

clean_up () {{
    XAUTHORITY={AUTH_FILE} xauth remove :{DISPLAY} >/dev/null 2>&1
    kill $(cat $XVFB_PID_FILE) >/dev/null 2>&1
}}

trap clean_up EXIT

start_x11 () {{
    # Appropriated from xvfb-run

    touch {AUTH_FILE}
    XAUTHORITY={AUTH_FILE} {XAUTH} add :{DISPLAY} . {MCOOKIE}

    # Handle SIGUSR1 so Xvfb knows to send a signal when ready. I don't really
    # understand how this was supposed to be handled by the code below, but
    # xvfb-run did it like this so ...

    trap : USR1
    (trap '' USR1;
     exec {XVFB} :{DISPLAY} -nolisten tcp  \
                            -auth {AUTH_FILE}  \
                            -fbdir /tmp -screen 0 {RESOLUTION}x16  \
        >/dev/null 2>&1) &
    XVFB_PID=$!
    echo $XVFB_PID > $XVFB_PID_FILE
    wait || :

    if ! kill -0 $XVFB_PID 2>/dev/null; then
        echo 'ERROR: Xvfb failed to start'
        echo 1 > $RETVAL_FILE
        return 1
    fi

    set +e
    DISPLAY=:{DISPLAY} XAUTHORITY={AUTH_FILE} sh -c '{ARGV}'
    echo $? > $RETVAL_FILE
    set -e
}}

start_ffmpeg () {{
    [ "{VIDEO_FILE}" ] || return
    ffmpeg -y -nostats -hide_banner -loglevel fatal -r 25 \
           -f x11grab -s {RESOLUTION} -i :{DISPLAY} {VIDEO_FILE} </dev/null &
    echo $! > $FFMPEG_PID_FILE
}}

kill_ffmpeg () {{
    [ "{VIDEO_FILE}" ] || return
    kill $(cat $FFMPEG_PID_FILE) 2>/dev/null
}}

# WTF: For some reason variables don't retain values across functions ???
TMPDIR=${{TMPDIR:-/tmp/}}
FFMPEG_PID_FILE=$(mktemp $TMPDIR/pyqttester.ffmpeg.XXXXXXX)
XVFB_PID_FILE=$(mktemp $TMPDIR/pyqttester.xvfb.XXXXXXX)
RETVAL_FILE=$(mktemp $TMPDIR/pyqttester.retval.XXXXXXX)

# First start the Xvfb instance, replaying the scenario inside.
# Right afterwards, start screengrabbing the Xvfb session with ffmpeg.
# When the scenario completes, kill ffmpeg as well.

{{ start_x11; kill_ffmpeg; }} & start_ffmpeg ; wait

RETVAL=$(cat $RETVAL_FILE)
rm $FFMPEG_PID_FILE #RETVAL_FILE
exit $RETVAL

'''


def parse_args():
    from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
    argparser = ArgumentParser(
        description='A tool for testing PyQt GUI applications by recording '
                    'and replaying scenarios.',
        formatter_class=ArgumentDefaultsHelpFormatter,
    )
    argparser.add_argument(
        '--verbose', '-v', action='count',
        help='Print verbose information (use twice for debug).')
    argparser.add_argument(
        '--log', metavar='FILE',
        help='Log program output.')

    subparsers = argparser.add_subparsers(
        title='Sub-commands', dest='_subcommand',
        help='Use --help for additional sub-command arguments.')
    parser_record = subparsers.add_parser(
        'record',
        formatter_class=ArgumentDefaultsHelpFormatter,
        help='Record the events the user sends to the entry-point application '
             'into the scenario file.')
    parser_replay = subparsers.add_parser(
        'replay',
        formatter_class=ArgumentDefaultsHelpFormatter,
        help='Replay the recorded scenario.')
    parser_explain = subparsers.add_parser(
        'explain',
        formatter_class=ArgumentDefaultsHelpFormatter,
        help='Explain in semi-human-readable form the events scenario contains.')

    # TODO: default try to figure out Qt version by grepping entry-point
    args, kwargs = (
        ('--qt',),
        dict(metavar='QT_VERSION', default='5', choices='45',
             help='The version of PyQt to run the entry-point app with (4 or 5).'))
    parser_record.add_argument(*args, **kwargs)
    parser_replay.add_argument(*args, **kwargs)

    args, kwargs = (
        ('scenario',),
        dict(metavar='SCENARIO',
             help='The scenario file.'))
    parser_record.add_argument(*args, **kwargs)
    parser_replay.add_argument(*args, **kwargs)
    parser_explain.add_argument(*args, **kwargs)

    args, kwargs = (
        ('main',),
        dict(metavar='MODULE_PATH',
             help='The application entry point (module.path.to:main function).'))
    parser_record.add_argument(*args, **kwargs)
    parser_replay.add_argument(*args, **kwargs)

    args, kwargs = (
        ('args',),
        dict(metavar='ARGS',
             nargs='*',
             help='Additional arguments to pass to the app as sys.argv.'))
    parser_record.add_argument(*args, **kwargs)
    parser_replay.add_argument(*args, **kwargs)

    parser_record.add_argument(
        '--events-include', metavar='REGEX',
        default=r'MouseEvent,KeyEvent,CloseEvent',  # TODO: add Drag, Focus, Hover ?
        help='When recording, record only events that match the filter.')
    parser_record.add_argument(
        '--events-exclude', metavar='REGEX',
        help="When recording, skip events that match the filter.")
    parser_record.add_argument( # TODO
        '--objects-include', metavar='REGEX',
        help='When recording, record only events on objects that match the filter.')
    parser_record.add_argument( # TODO
        '--objects-exclude', metavar='REGEX',
        help="When recording, skip events on objects that match the filter.")

    parser_replay.add_argument(
        '--x11', action='store_true',
        help=('When replaying scenarios, do it in a new, headless X11 server. '
              "This makes your app's stdout piped to stderr."))
    parser_replay.add_argument(
        '--x11-video', metavar='FILE', nargs='?', const=True,
        help='Record the video of scenario playback into FILE (default: SCENARIO.mp4).')
    parser_replay.add_argument( # TODO
        '--coverage', action='store_true',
        help='Run the coverage analysis simultaneously.')

    args = argparser.parse_args()

    def init_logging(verbose=0, log_file=None):
        import logging
        global log
        log = logging.getLogger(__name__)
        formatter = logging.Formatter('%(relativeCreated)d %(levelname)s: %(message)s')
        for handler in (logging.StreamHandler(),
                        log_file and logging.FileHandler(log_file, 'w', encoding='utf-8')):
            if handler:
                handler.setFormatter(formatter)
                log.addHandler(handler)
        log.setLevel(logging.WARNING - 10 * verbose)

    init_logging(args.verbose or 0, args.log)
    log.info('Program arguments: %s', args)

    def _error(*args, **kwargs):
        log.error(*args, **kwargs)
        REAL_EXIT(1)

    def _is_command_available(command):
        try: return 0 == subprocess.call(['which', command], stdout=subprocess.DEVNULL)
        except OSError: return False

    def _check_main(args):

        def _main(entry_point=args.main):
            # Make the application believe it was run unpatched
            sys.argv = [entry_point] + args.args
            try:
                module, main = entry_point.split(':')
                log.debug('Importing module %s ...', module)
                module = import_module(module)
                main = deepgetattr(module, main)
                if not callable(main):
                    raise ValueError
            except ValueError:
                _error('MODULE_PATH must be like module.path.to:main function')
            else:
                log.info('Running %s', entry_point)
                main()

        args.main = _main

    def _global_qt(args):
        global QtGui, QtCore, QWidget, Qt, qApp, QT_KEYS, EVENT_TYPE
        PyQt = 'PyQt' + str(args.qt)
        QtGui = import_module(PyQt + '.QtGui')
        QtCore = import_module(PyQt + '.QtCore')
        Qt = QtCore.Qt
        try:
            QWidget = QtGui.QWidget
            qApp = QtGui.qApp
        except AttributeError:  # PyQt5
            QtWidgets = import_module(PyQt + '.QtWidgets')
            QWidget = QtWidgets.QWidget
            qApp = QtWidgets.qApp
        QT_KEYS = {value: 'Qt.' + key
                   for key, value in Qt.__dict__.items()
                   if key.startswith('Key_')}
        EVENT_TYPE = {v: k
                      for k, v in QtCore.QEvent.__dict__.items()
                      if isinstance(v, int)}
        # This is just a simple unit test. Put here because real Qt has only
        # been made available above.
        assert 'Qt.LeftButton|Qt.RightButton' == \
               Resolver._qflags_key(Qt, Qt.LeftButton | Qt.RightButton)

    def check_explain(args):
        try: args.scenario = open(args.scenario, 'rb')
        except (IOError, OSError) as e:
            _error('explain %s: %s', args.scenario, e)

    def check_record(args):
        _check_main(args)
        _global_qt(args)
        try: args.scenario = open(args.scenario, 'wb')
        except (IOError, OSError) as e:
            _error('record %s: %s', args.scenario, e)

    def check_replay(args):
        _check_main(args)
        _global_qt(args)
        try: args.scenario = open(args.scenario, 'rb')
        except (IOError, OSError) as e:
            _error('replay %s: %s', args.scenario, e)
        # TODO: https://coverage.readthedocs.org/en/coverage-4.0.2/api.html#api
        #       https://nose.readthedocs.org/en/latest/plugins/cover.html#source
        if args.x11_video:
            if not _is_command_available('ffmpeg'):
                _error('Recording video of X11 session (--x11-video) requires '
                       'ffmpeg. Install package ffmpeg.')
            if not args.x11:
                log.warning('--x11-video implies --x11')
                args.x11 = True
            if args.x11_video is True:
                args.x11_video = args.scenario.name + '.mp4'
        if args.x11:
            for xvfb in ('Xvfb', '/usr/X11/bin/Xvfb'):
                if _is_command_available(xvfb):
                    break
            else: _error('Headless X11 (--x11) requires working Xvfb. '
                         'Install package xvfb (or XQuartz on a Macintosh).')
            for xauth in ('xauth', '/usr/X11/bin/xauth'):
                if _is_command_available(xauth):
                    break
            else: _error('Headless X11 (--x11) requires working xauth. '
                         'Install package xauth (or XQuartz on a Macintosh).')

            log.info('Re-running head-less in Xvfb.')
            # Prevent recursion
            for arg in ('--x11', '--x11-video'):
                try: sys.argv.remove(arg)
                except ValueError: pass

            from random import randint
            from hashlib import md5
            command_line = SHELL_SCRIPT.format(
                    VIDEO_FILE=args.x11_video,
                    RESOLUTION='1280x1024',
                    SCENARIO=args.scenario.name,
                    AUTH_FILE=os.path.join(os.path.expanduser('~'), '.Xauthority'),
                    XVFB=xvfb,
                    XAUTH=xauth,
                    MCOOKIE=md5(os.urandom(30)).hexdigest(),
                    DISPLAY=next(i for i in (randint(111, 10000) for _ in repeat(0))
                                 if not os.path.exists('/tmp/.X{}-lock'.format(i))),
                    ARGV=' '.join(sys.argv))
            REAL_EXIT(subprocess.call(command_line, shell=True, stdout=sys.stderr))

    try:
        dict(record=check_record,
             replay=check_replay,
             explain=check_explain)[args._subcommand](args)
    except KeyError:
        return REAL_EXIT(argparser.format_help())
    return args


PathElement = namedtuple('PathElement', ('index', 'type', 'name'))


class Resolver:

    class IdentityMapper:
        def __getitem__(self, key):
            return key

    def __init__(self, obj_cache):
        self.id_obj_map = obj_cache if obj_cache is not None else self.IdentityMapper()
        self.obj_id_map = {}
        self.autoinc = count(1)

    @staticmethod
    def _qenum_key(base, value, klass=None):
        """Return Qt enum value as string name of its key.

        Modelled after code by Florian "The Compiler" Bruhin:
        https://github.com/The-Compiler/qutebrowser/blob/master/qutebrowser/utils/debug.py#L91-L167

        Parameters
        ----------
        base: type
            The type object the enum is in, e.g. QFrame or QtCore.Qt.
        value: enum value (int)
            The value of the enum, e.g. Qt.LeftButton
        klass: type
            The enum class the value belongs to, or None to auto-guess.

        Returns
        -------
        key: str
            The key associated with the value if found or '' otherwise.

        Example
        -------
        >>> _qenum_key(Qt, Qt.LeftButton)
        'Qt.LeftButton'
        >>> _qenum_key(Qt, Qt.LeftButton | Qt.RightButton)
        ''
        """
        klass = klass or type(value)

        if klass == int:  # Can't guess enum class of an int
            return ''

        meta_object = getattr(base, 'staticMetaObject', None)
        if meta_object:
            enum = meta_object.indexOfEnumerator(klass.__name__)
            key = meta_object.enumerator(enum).valueToKey(value)
        else:
            try:
                key = next(name for name, obj in base.__dict__.items()
                           if isinstance(obj, klass) and obj == value)
            except StopIteration:
                key = ''
        return (base.__name__ + '.' + key) if key else ''

    @classmethod
    def _qflags_key(cls, base, value, klass=None):
        """Convert a Qt QFlags value to its keys as '|'-separated string.

        Modelled after code by Florian "The Compiler" Bruhin:
        https://github.com/The-Compiler/qutebrowser/blob/master/qutebrowser/utils/debug.py#L91-L167

        Parameters
        ----------
        base: type
            The type object the flags are in, e.g. QtCore.Qt
        value: int
            The flags value to convert to string.
        klass: type
            The flags class the value belongs to, or None to auto-guess.

        Returns
        -------
        keys: str
            The keys associated with the flags as a '|'-separated string
            if they were found; '' otherwise.

        Note
        ----
        Passing a combined value (e.g. Qt.AlignCenter) will get the names
        of the individual bits (Qt.AlignVCenter | Qt.AlignHCenter).

        Bugs
        ----
        https://github.com/The-Compiler/qutebrowser/issues/42
        """
        klass = klass or type(value)
        if klass == int:
            return ''
        if klass.__name__.endswith('s'):
            klass = getattr(base, klass.__name__[:-1])
        keys = []
        mask = 1
        value = int(value)
        while mask <= value:
            if value & mask:
                keys.append(cls._qenum_key(base, klass(mask), klass=klass))
            mask <<= 1
        if not keys and value == 0:
            keys.append(cls._qenum_key(base, klass(0), klass=klass))
        return '|'.join(filter(None, keys))

    @classmethod
    def _serialize_value(cls, value, attr):
        """Return str representation of value for attribute attr."""
        value_type = type(value)
        if value_type == int:
            if attr == 'key':
                global QT_KEYS
                return QT_KEYS[value]
            return str(value)
        if value_type == str:
            return repr(value)
        if value_type == bool:
            return str(value)
        # QPoint/QRect (...) values are pickleable directly according to PyQt
        # docs. The reason they are not used like this here is consistency and
        # smaller size. Yes, this string is >100% more light-weight.
        if isinstance(value, (QtCore.QPointF, QtCore.QPoint)):
            return 'QtCore.{}({}, {})'.format(type(value).__name__,
                                              value.x(),
                                              value.y())
        if isinstance(value, (QtCore.QRectF, QtCore.QRect)):
            return 'QtCore.{}({}, {}, {}, {})'.format(type(value).__name__,
                                                      value.x(),
                                                      value.y(),
                                                      value.width(),
                                                      value.height())
        # Perhaps it's an enum value from Qt namespace
        assert isinstance(Qt.LeftButton, int)
        if isinstance(value, int):
            s = cls._qenum_key(Qt, value)
            if s: return s
        # Finally, if it ends with 's', it's probably a QFlags object
        # combining the flags of associated Qt.<name-without-s> type, e.g.
        # bitwise or-ing Qt.MouseButton values (Qt.LeftButton | Qt.RightButton)
        # makes a Qt.MouseButtons object:
        assert isinstance((Qt.LeftButton | Qt.RightButton), Qt.MouseButtons)
        if type(value).__name__.endswith('s'):
            s = cls._qflags_key(Qt, value)
            if s:
                return s

        raise ValueError

    EVENT_ATTRIBUTES = {
        # Q*Event attributes, ordered as the constructor takes them
        'QMouseEvent':'type pos globalPos button buttons modifiers'.split(),
        'QKeyEvent': 'type key modifiers text isAutoRepeat count'.split(),
        'QMoveEvent': 'pos oldPos'.split(),
        'QCloseEvent': [],
    }

    @classmethod
    def serialize_event(cls, event) -> str:
        assert isinstance(event, QtCore.QEvent)

        event_type = type(event)
        event_attributes = cls.EVENT_ATTRIBUTES.get(event_type.__name__, ('type',))
        if not event_attributes:
            log.warning('Missing fingerprint for event: %s, type=%s, mro=%s',
                        event_type, event.type(), event_type.__mro__)

        args = []
        if event_attributes and event_attributes[0] == 'type':
            args.append('QtCore.' + cls._qenum_key(QtCore.QEvent, event.type()))
            # Skip first element (type) in the loop ahead
            event_attributes = iter(event_attributes); next(event_attributes)
        for attr in event_attributes:
            value = getattr(event, attr)()
            try: args.append(cls._serialize_value(value, attr))
            except ValueError:
                args.append('0b0')
                log.warning("Can't serialize object %s of type %s "
                            "for attribute %s. Inserting a 0b0 (zero) instead.",
                            value, type(value).__mro__, attr)
        event_str = event_type.__name__ + '(' + ', '.join(args) + ')'
        log.info('Serialized event: %s', event_str)
        return event_str

    @staticmethod
    def deserialize_event(event_str):
        try:
            return eval('QtGui.' + event_str)
        except AttributeError:
            return eval('QtCore.' + event_str)

    @staticmethod
    @lru_cache()
    def serialize_type(type_obj):
        """Return fully-qualified name of type, or '' if translation not reversible"""
        type_str = type_obj.__module__ + ':' + type_obj.__qualname__
        return type_str if '.<locals>.' not in type_str else ''

    @staticmethod
    @lru_cache()
    def deserialize_type(type_str):
        """Return type object that corresponds to type_str"""
        module, qualname = type_str.split(':')
        return deepgetattr(import_module(module), qualname)

    @classmethod
    def _get_children(cls, widget):
        """
        Get all children widgets of widget. Children are if they're in widget's
        layout, or if the widget splits them, or if they are QObject children
        of widget, or similar.
        """
        if widget is None:
            yield from qApp.topLevelWidgets()

        if isinstance(widget, QtGui.QSplitter):
            yield from (widget.widget(i) for i in range(widget.count()))
            yield from (widget.handle(i) for i in range(widget.count()))

        layout = hasattr(widget, 'layout') and widget.layout()
        if layout:
            yield from (layout.itemAt(i).widget()
                        for i in range(layout.count()))

        if hasattr(widget, 'children'):
            yield from widget.children()

        # If widget can't be found in the hierarchy by Qt means,
        # try Python object attributes
        yield from (getattr(widget, attr)
                    for attr in dir(widget)
                    if not attr.startswith('__') and attr.endswith('__'))

    @classmethod
    def serialize_object(cls, obj):
        assert isinstance(obj, QWidget)

        path = []
        parent = obj
        while parent is not None:
            widget, parent = parent, parent.parentWidget()
            children = cls._get_children(parent)
            # This typed index is more resilient than simple layout.indexOf()
            typed_widgets = (w for w in children if type(w) == type(widget))
            index = next((i for i, w in enumerate(typed_widgets) if w is widget), None)

            if index is None:
                # FIXME: What to do here instead?
                if path:
                    log.warning('Skipping object path: %s -> %s', obj,
                                path)
                path = ()
                break
            path.append(PathElement(index,
                                    cls.serialize_type(type(widget)),
                                    widget.objectName()))
        assert (not path or
                len(path) > 1 or
                len(path) == 1 and obj in qApp.topLevelWidgets())
        if path:
            path = tuple(reversed(path))
            log.info('Serialized object path: %s', path)
        return path

    @classmethod
    def _find_by_name(cls, target):
        return (qApp.findChild(cls.deserialize_type(target.type), target.name) or
                next(widget for widget in qApp.allWidgets()
                     if widget.objectName() == target.name))

    @classmethod
    def deserialize_object(cls, path):
        target = path[-1]
        target_type = cls.deserialize_type(target.type)

        # Find target object by name
        if target.name:
            try:
                return cls._find_by_name(target)
            except StopIteration:
                log.warning('Name "%s" provided, but no *widget* with that name '
                            'found. If the test passes, its result might be '
                            'invalid, or the test may just need updating.',
                            target.name)

        # If target widget doesn't have a name, find it in the tree
        def get_child(i, widgets):
            element = path[i]
            widget = typed_nth(element.index,
                               cls.deserialize_type(element.type),
                               widgets)
            if element == target or widget is None:
                return widget
            return get_child(i + 1, cls._get_children(widget))

        return get_child(0, qApp.topLevelWidgets())

    def getstate(self, obj, event):
        """Return picklable state of the object and its event"""
        obj_path = self.serialize_object(obj)
        if not obj_path:
            log.warning('Skipping object: %s', obj)
            return None
        event_str = self.serialize_event(event)
        if not event_str:
            log.warning('Skipping event: %s', event)

        obj_id = self.obj_id_map.get(obj_path)
        if obj_id is None:
            obj_id = next(self.autoinc)
            self.obj_id_map[obj_path] = obj_id
            self.id_obj_map[obj_id] = obj_path
        return (obj_id, event_str)

    def setstate(self, obj_id, event_str):
        obj_path = self.id_obj_map[obj_id]
        obj = self.deserialize_object(obj_path)
        if obj is None:
            log.error("Can't replay event %s on object %s: Object not found",
                      event_str, obj_path)
            REAL_EXIT(3)
        event = self.deserialize_event(event_str)
        log.info('Replaying event %s on object %s',
                 event_str, obj_path)
        return qApp.sendEvent(obj, event)

    def print_state(self, i, obj_id, event_str):
        obj_path = self.id_obj_map[obj_id]
        print('Event', str(i) + ':', event_str.replace('QtCore.', ''))
        print('Object:')
        for indent, el in enumerate(obj_path):
            print('  '*(indent + 1),
                  el.index,
                  repr(el.name) if el.name else '',
                  el.type)
        print()


class _EventFilter:
    @staticmethod
    def wait_for_app_start(method):
        is_started = False

        def f(self, obj, event):
            nonlocal is_started
            if not is_started:
                log.debug('Caught %s (%s) event but app not yet fully "started"',
                          EVENT_TYPE.get(event.type(),
                                         'QEvent(type=' + str(event.type()) + ')'),
                          type(event).__name__)
                if event.type() == QtCore.QEvent.ActivationChange:
                    log.debug("Ok, app is started now, don't worry")
                    is_started = True
            # With the following return in place, Xvfb sometimes got stuck
            # before any serious events happened. I suspected WM (or lack
            # thereof) being the culprit, so now we spawn a WM that sends
            # focus, activation events, ... This seems to have fixed it once.
            # I think this return (False) should be here (instead of proceeding
            # with the filter method).
            return method(self, obj, event) if is_started else False
        return f

    def close(self):
        pass


class EventRecorder(_EventFilter):
    def __init__(self, file, events_include, events_exclude):
        super().__init__()
        self.file = file

        # Prepare the recorded events stack;
        # the first entry is the protocol version
        self.events = [SCENARIO_FORMAT_VERSION]
        obj_cache = {}
        self.events.append(obj_cache)

        self.resolver = Resolver(obj_cache)

        is_included = (re.compile('|'.join(events_include.split(','))).search
                       if events_include else lambda _: True)
        is_excluded = (re.compile('|'.join(events_exclude.split(','))).search
                       if events_exclude else lambda _: False)

        def event_matches(event_name):
            return is_included(event_name) and not is_excluded(event_name)

        self.event_matches = event_matches

    @_EventFilter.wait_for_app_start
    def eventFilter(self, obj, event):
        # Only process out-of-application, system (e.g. X11) events
        # if not event.spontaneous():
        #     return False
        is_skipped = (not self.event_matches(type(event).__name__) or
                      not isinstance(obj, QWidget))  # FIXME: This condition is too strict (QGraphicsItems are QOjects)
        log_ = log.debug if is_skipped else log.info
        log.info('Caught %s%s %s event (%s) on object %s',
                 'skipped' if is_skipped else 'recorded',
                 ' spontaneous' if event.spontaneous() else '',
                 EVENT_TYPE.get(event.type(),
                                'Unknown(type=' + str(event.type()) + ')'),
                 event.__class__.__name__, obj)
        # Before any event on any widget, make sure the window of that window
        # is active and raised (in front). This is required for replaying
        # without a window manager.
        if (isinstance(obj, QWidget) and
                event.type() != QtCore.QEvent.MouseMove and
                not is_skipped and
                not obj.isActiveWindow() and
                event.spontaneous()):
            obj.activateWindow()
        if not is_skipped:
            serialized = self.resolver.getstate(obj, event)
            if serialized:
                self.events.append(serialized)
        return False

    def close(self):
        """Write out the scenario"""
        log.debug('Writing scenario file')
        pickle.dump(self.events, self.file, protocol=0)
        log.info("Scenario of %d events written into '%s'",
                 len(self.events) - SCENARIO_FORMAT_VERSION - 1, self.file.name)
        log.debug(self.events)


class EventReplayer(_EventFilter):
    def __init__(self, file):
        super().__init__()
        # Replay events X ms after the last event
        self.timer = QtCore.QTimer(self, interval=50)
        self.timer.timeout.connect(self.replay_next_event)
        self.load(file)

    def load(self, file):
        self._events = pickle.load(file)
        self.events = iter(self._events)
        format_version = next(self.events)
        obj_cache = next(self.events) if format_version > 0 else None
        self.resolver = Resolver(obj_cache)

    @_EventFilter.wait_for_app_start
    def eventFilter(self, obj, event):
        if (event.type() == QtCore.QEvent.Timer and
                event.timerId() == self.timer.timerId()):
            # Skip self's timer events
            return False
        log.debug('Caught %s (%s) event; resetting timer',
                  EVENT_TYPE.get(event.type(), 'Unknown(type=' + str(event.type()) + ')'),
                  type(event))
        self.timer.stop()
        self.timer.start()
        return False

    def replay_next_event(self):
        # TODO: if timer took too long (significantly more than its interval)
        # perhaps there was a busy loop in the code; better restart it
        self.timer.stop()
        event = next(self.events, None)
        if not event:
            log.info('No more events to replay.')
            QtGui.qApp.quit()
            return
        log.debug('Replaying event: %s', event)
        self.resolver.setstate(*event)
        return False

    def close(self):
        remaining_events = list(self.events)
        if remaining_events:
            log.warning("Application didn't manage to replay all events. "
                        "This may indicate failure. But not necessarily. :|")
            log.info("The remaining events are: %s", remaining_events)


class EventExplainer:
    def __init__(self, file):
        self._events = pickle.load(file)
        self.events = iter(self._events)
        format_version = next(self.events)
        obj_cache = next(self.events) if format_version > 0 else None
        self.resolver = Resolver(obj_cache)

    def run(self):
        for i, event in enumerate(self.events):
            self.resolver.print_state(i, *event)


def EventFilter(type, *args):
    """
    Return an instance of type'd filter with closure over correct
    (PyQt4's or PyQt5's) version of QtCore.QObject.
    """
    class EventFilter(type, QtCore.QObject):
        """
        This class is a wrapper around above EventRecorder / EventReplayer.
        Qt requires that the object that filters events with eventFilter() is
        (also) a QObject.
        """
        def eventFilter(self, obj, event):
            return super().eventFilter(obj, event)

    return EventFilter(*args)


def main():
    args = parse_args()

    if args._subcommand == 'explain':
        explainer = EventExplainer(args.scenario)
        explainer.run()
        return 0

    event_filters = []
    if args._subcommand == 'record':
        recorder = EventFilter(EventRecorder,
                               args.scenario,
                               args.events_include,
                               args.events_exclude)
        event_filters.append(recorder)
    if args._subcommand == 'replay':
        replayer = EventFilter(EventReplayer, args.scenario)
        event_filters.append(replayer)

    assert event_filters

    # Patch QApplication to filter all events through EventRecorder / EventReplayer
    class QApplication(QtGui.QApplication):
        def __init__(self, *args, **kwargs):
            # Before constructing the application, prevent the application of
            # any custom, desktop environment-dependent styles and settings.
            # We can only reproduce scenarios if everyone is running them
            # the same.
            QApplication.setDesktopSettingsAware(False)
            super().__init__(*args, **kwargs)
            for event_filter in event_filters:
                log.debug('Installing event filter: %s',
                          type(event_filter).mro()[1].__name__)
                self.installEventFilter(event_filter)
    QtGui.QApplication = QApplication

    # Prevent exit with zero status from inside the app. We need to exit from this app.
    def exit(status=0):
        log.warning('Prevented call to sys.exit() with status: %s', str(status))
        if status != 0:
            log.warning('But the exit status was non-zero, so quitting')
            REAL_EXIT(status)
    sys.exit = exit

    # Qt doesn't raise exceptions out of its event loop; but this works
    def excepthook(type, value, tback):
        import traceback
        log.error('Unhandled exception encountered')
        traceback.print_exception(type, value, tback)
        REAL_EXIT(2)
    sys.excepthook = excepthook

    # Allow termination with Ctrl+C
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    # Execute the app
    args.main()

    log.info('Application exited successfully. Congrats!')

    for event_filter in event_filters:
        event_filter.close()
    return 0

if __name__ == '__main__':
    REAL_EXIT(main())
