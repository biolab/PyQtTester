#!/usr/bin/env python3

import sys; REAL_EXIT = sys.exit
import os
import re
import subprocess
from functools import reduce, wraps
from collections import namedtuple
from itertools import chain, islice, count
from importlib import import_module

try: import cPickle as pickle
except ImportError: import pickle

# Allow termination with Ctrl+C
import signal; signal.signal(signal.SIGINT, signal.SIG_DFL)

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


def parse_args():
    # WM must be compatible (probably click-to-focus, ...
    # — I don't know, but most WMs I tried didn't work)
    WINDOW_MANAGERS = ('windowlab',)

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
        '--qt', metavar='QT_VERSION', default='5', choices='45',
        help='The version of PyQt to run the entry-point app with (4 or 5).')
        # TODO: default try to figure out Qt version by grepping entry-point
    group = argparser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--record', metavar='SCENARIO',
        help='Record the events the user sends to the entry-point application '
             'into the scenario file.')
    group.add_argument(
        '--replay', metavar='SCENARIO',
        help='Replay the scenario.')
    group.add_argument(
        '--info', metavar='SCENARIO',
        help='Explain in semi-human-readable form events the scenario contains.')
    argparser.add_argument(
        '--main', '-m', metavar='MODULE_PATH',
        help='The application entry point (module.path.to:main function).')
    argparser.add_argument(
        '--events-include', metavar='FILTER',
        default=r'MouseEvent,KeyEvent', # 'Drag,Focus,Hover'
        help='When recording, record only events that match the (regex) filters.')
    argparser.add_argument(
        '--events-exclude', metavar='FILTER',
        help="When recording, skip events that match the (regex) filters.")
    argparser.add_argument( # TODO
        '--objects-include', metavar='FILTER',
        help='When recording, record only events on objects that match the (regex) filters.')
    argparser.add_argument( # TODO
        '--objects-exclude', metavar='FILTER',
        help="When recording, skip events on objects that match the (regex) filter.")
    argparser.add_argument( # TODO
        '--fuzzy', action='store_true',
        help='Fuzzy-matching of event target objects.')
    argparser.add_argument(
        '--x11', action='store_true',
        help=('When replaying scenarios, do it in a new, headless X11 server. '
              "This makes your app's stdout piped to stderr. "
              "It will work better (or at all) if you make one of the following "
              "window managers available: " + ', '.join(WINDOW_MANAGERS)) + '.')
    argparser.add_argument(
        '--x11-video', metavar='FILE', nargs='?', const=True,
        help='Record the video of scenario playback into FILE (default: SCENARIO.mp4).')
    argparser.add_argument( # TODO
        '--coverage', action='store_true',
        help='Run the coverage analysis simultaneously.')
    argparser.add_argument(
        '--log', metavar='FILE',
        help='Save the program output into file.')
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

    def error(*args, **kwargs):
        log.error(*args, **kwargs)
        REAL_EXIT(1)

    if args.record or args.replay:
        if not args.main:
            error('--record/--replay requires --main ("module.path.to.main" function)')

        def _main(entry_point=args.main):
            # Make the application believe it was run unpatched
            sys.argv = [entry_point]  # TODO is this ok??
            try:
                module, main = entry_point.split(':')
                log.debug('Importing module %s ...', module)
                module = import_module(module)
                main = deepgetattr(module, main)
                if not callable(main):
                    raise ValueError
            except ValueError:
                error('--main must be like module.path.to:main function')
            else:
                log.info('Running %s', entry_point)
                main()

        args.main = _main
    if args.record:
        try: args.record = open(args.record, 'wb')
        except Exception as e:
            error('--record: %s', e)
    if args.replay:
        try: args.replay = open(args.replay, 'rb')
        except Exception as e:
            error('--replay: %s', e)
    if args.info:
        try: args.info = open(args.info, 'rb')
        except Exception as e:
            error('--info: %s', e)
    if args.coverage:
        # TODO: https://coverage.readthedocs.org/en/coverage-4.0.2/api.html#api
        #       https://nose.readthedocs.org/en/latest/plugins/cover.html#source
        ...

    def is_command_available(command):
        try:
            if 0 != subprocess.call(command, shell=True, stdout=subprocess.DEVNULL):
                raise OSError
        except OSError:
            return False
        return True

    if args.x11_video:
        if not is_command_available('ffmpeg --help'):
            error('Recording video of X11 session (--x11-video) requires working '
                  'ffmpeg. Install package ffmpeg.')
        if not args.replay:
            error('--x11-video requires --replay')
        if not args.x11:
            log.warning('--x11-video implies --x11')
            args.x11 = True
        if args.x11_video is True:
            args.x11_video = args.replay.name + '.mp4'
    if args.x11:
        if not args.replay:
            error('--x11 requires --replay')
        # Escalate the power of shell
        if not is_command_available('xvfb-run --help'):
            error('Headless X11 (--x11) requires working xvfb-run. Install package xvfb.')
        log.info('Re-running head-less in Xvfb. '
                 # The following cannot be avoided because Xvfb writes all app's
                 # output, including stderr, to stdout
                 'All subprocess output (including stdout) will be piped to stderr.')
        # Prevent recursion
        for arg in ('--x11',
                    '--x11-video'):
            try: sys.argv.remove(arg)
            except ValueError: pass

        command_line = r'''
start_x11 () {{
    xvfb-run --server-args '-fbdir /tmp -screen 0 {RESOLUTION}x16'  \
             --auth-file {AUTH_FILE}  \
             --server-num {DISPLAY}   \
             sh -c '{WINDOW_MANAGERS}
                    sleep .5;
                    {ARGV}'
}}

start_ffmpeg () {{
    [ "{VIDEO_FILE}" ] || return
    ffmpeg -y -nostats -hide_banner -loglevel fatal -r 25 \
           -f x11grab -s {RESOLUTION} -i :{DISPLAY} {VIDEO_FILE} </dev/null &
    echo $! > $FFMPEG_PID_FILE
}}

kill_ffmpeg () {{
    [ "{VIDEO_FILE}" ] || return
    FFMPEG_PID=$(cat $FFMPEG_PID_FILE)
    kill -TERM $FFMPEG_PID
}}

# First start the Xvfb instance, replaying the scenario inside.
# Right afterwards, start screengrabbing the Xvfb session with ffmpeg.
# When the scenario completes, kill ffmpeg as well.

FFMPEG_PID_FILE=$(mktemp)
{{ start_x11; kill_ffmpeg; }} & start_ffmpeg ; wait
rm $FFMPEG_PID_FILE

'''.format(VIDEO_FILE=args.x11_video,
           RESOLUTION='1280x1024',
           SCENARIO=args.replay.name,
           AUTH_FILE=os.path.join(os.path.expanduser('~'), '.Xauthority'),
           DISPLAY=next(i for i in range(111, 1000)
                        if not os.path.exists('/tmp/.X{}-lock'.format(i))),
           WINDOW_MANAGERS=' '.join('{} 2>/dev/null &'.format(wm)
                                    for wm in WINDOW_MANAGERS),
           ARGV=' '.join(sys.argv))

        REAL_EXIT(subprocess.call(command_line, shell=True, stdout=sys.stderr))
    return args


PathElement = namedtuple('PathElement', ('index', 'type', 'name'))


class Resolver:
    FUZZY_MATCHING = False

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
        if event_str.startswith('QEvent('):   # Generic, unspecialized QEvent
            event = eval('QtCore.' + event_str)  # FIXME: deprecate?
        else:
            event = eval('QtGui.' + event_str)
        return event

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
        if not widget:
            return qApp.topLevelWidgets()

        parts = []

        if isinstance(widget, QtGui.QSplitter):
            parts.append(widget.widget(i) for i in range(widget.count()))
            parts.append(widget.handle(i) for i in range(widget.count()))

        layout = getattr(widget, 'layout', lambda: None)()
        if layout:
            parts.append(layout.itemAt(i).widget()
                         for i in range(layout.count()))

        parts.append(getattr(widget, 'children', lambda: ())())

        return chain.from_iterable(parts)

    @classmethod
    def serialize_object(cls, obj):
        assert isinstance(obj, QWidget)

        path = []
        parent = obj
        while parent:
            widget, parent = parent, parent.parentWidget()
            children = cls._get_children(parent)
            # This typed index is more resilient than simple layout.indexOf()
            index = next((i for i, w in enumerate(w for w in children
                                                  if type(w) == type(widget))
                          if w is widget), None)
            # If widget can't be found in the hierarchy by Qt means,
            # try Python object attributes
            if index is None:
                children = cls._get_attr_children(parent)
                index = next((k for k, v in children.items() if v is widget), None)

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
        def candidates(i, widgets):
            # TODO: make this function nicer
            target = path[i]
            target_type = cls.deserialize_type(target.type)
            if i == len(path) - 1:
                # This is the last element in the path, the true target
                return iter((nth(target.index,
                                 (w for w in widgets if type(w) == target_type)),))
            return candidates(i + 1,
                              cls._get_children(nth(target.index,
                                                    (w for w in widgets
                                                     if type(w) == target_type))))

        # target_with_name = next((i for i in reversed(path) if i.name), None)
        # if target_with_name:
        #     i = path.index(target_with_name)
        #     try:
        #         return next(candidates(i, (cls._find_by_name(target_with_name),)))
        #     except StopIteration:
        #         pass

        return next(candidates(0, qApp.topLevelWidgets()), None)

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
                log.debug(
                    'Caught %s (%s) event but app not yet fully "started"',
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


class EventRecorder(_EventFilter):
    def __init__(self, events_include, events_exclude):
        super().__init__()

        # Prepare the recorded events stack;
        # the first entry is the protocol version
        self.events = [SCENARIO_FORMAT_VERSION]
        obj_cache = {}
        self.events.append(obj_cache)

        self.resolver = Resolver(obj_cache)

        is_included = re.compile('|'.join(events_include.split(','))).search
        is_excluded = re.compile('|'.join(events_exclude.split(','))).search

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
             EVENT_TYPE.get(event.type(), 'Unknown(type=' + str(event.type()) + ')'),
             event.__class__.__name__, obj)
        # Before any event on any widget, make sure the window of that window
        # is active and in raised (in front). This is required for replaying
        # without a window manager.
        # if isinstance(obj, QWidget) and not obj.isActiveWindow():
        #     obj.activateWindow()

        if (isinstance(obj, QWidget) and
                not is_skipped and
                not obj.isActiveWindow() and
                event.spontaneous()):
            obj.activateWindow()
        if not is_skipped:
            serialized = self.resolver.getstate(obj, event)
            if serialized:
                self.events.append(serialized)
        return False

    def dump(self, file):
        log.debug('Writing scenario file')
        pickle.dump(self.events, file, protocol=0)
        log.info("Scenario of %d events written into '%s'",
                 len(self.events) - SCENARIO_FORMAT_VERSION - 1, file.name)
        log.info(self.events)


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

    # Set some global variables
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
    Resolver.FUZZY_MATCHING = args.fuzzy

    # This is just a simple unit test. Put here because real Qt has only
    # been made available above.
    assert 'Qt.LeftButton|Qt.RightButton' == \
           Resolver._qflags_key(Qt, Qt.LeftButton|Qt.RightButton)

    if args.info:
        explainer = EventExplainer(args.info)
        explainer.run()
        return 0

    event_filters = []
    if args.record:
        recorder = EventFilter(EventRecorder,
                               args.events_include or r'.',
                               args.events_exclude or r'^$')
        event_filters.append(recorder)
    if args.replay:
        replayer = EventFilter(EventReplayer, args.replay)
        event_filters.append(replayer)
    ...

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
            REAL_EXIT(status)
    sys.exit = exit

    # Qt doesn't raise exceptions out of its event loop; but this works
    def excepthook(type, value, tback):
        import traceback
        log.error('Unhandled exception encountered')
        traceback.print_exception(type, value, tback)
        REAL_EXIT(2)
    sys.excepthook = excepthook

    # Execute the app
    args.main()

    log.info('Application exited successfully. Congrats!')

    # Write out the scenario
    if args.record:
        recorder.dump(args.record)

    have_more_events = args.replay and list(replayer.events)
    if have_more_events:
        log.warning("Application didn't manage to replay all events. "
                    "This may indicate failure. :|")
        log.info("The remaining events are: %s", have_more_events)
    return 0

if __name__ == '__main__':
    REAL_EXIT(main())
