#!/usr/bin/env python3

import sys; REAL_EXIT = sys.exit
from functools import reduce, wraps
from collections import namedtuple
from itertools import chain
from importlib import import_module

# Allow termination with Ctrl+C
import signal; signal.signal(signal.SIGINT, signal.SIG_DFL)

try:
    from functools import lru_cache
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


SCENARIO_VERSION = 1


def deepgetattr(obj, attr):
    """Recurses through an attribute chain to get the ultimate value."""
    return reduce(getattr, attr.split('.'), obj)


def parse_args():
    # WM must be compatible (probably click-to-focus, ...
    # — I don't know, but most WMs I tried didn't work)
    WINDOW_MANAGERS = ('windowlab',)

    from argparse import ArgumentParser
    argparser = ArgumentParser()
    argparser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Print verbose (debug) information.')
    argparser.add_argument(
        '--qt', metavar='QT_VERSION', default='4', choices='45',
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
    group.add_argument( # TODO
        '--info', metavar='SCENARIO',
        help='Explain in human-readable form events the scenario contains.')
    argparser.add_argument(
        '--main', '-m', metavar='MODULE_PATH',
        help='The application entry point (module.path.to:main function).')
    argparser.add_argument( # TODO
        '--events-include', metavar='FILTER',
        help='When recording, record only events that match the filter.')
    argparser.add_argument( # TODO
        '--events-exclude', metavar='FILTER',
        help="When recording, skip events that match the filter.")
    argparser.add_argument( # TODO
        '--objects-include', metavar='FILTER',
        help='When recording, record only events on objects that match the filter.')
    argparser.add_argument( # TODO
        '--objects-exclude', metavar='FILTER',
        help="When recording, skip events on objects that match the filter.")
    argparser.add_argument(
        '--fuzzy', action='store_true',
        help='Fuzzy-matching of event target objects.')
    argparser.add_argument(
        '--x11', action='store_true',
        help=('When replaying scenarios, do it in a new, headless X11 server. '
              "This makes your app's stdout piped to stderr. "
              "It will work better (or at all) if you make one of the following "
              "window managers available: " + ', '.join(WINDOW_MANAGERS)) + '.')
    argparser.add_argument( # TODO
        '--coverage', action='store_true',
        help='Run the coverage analysis simultaneously.')
    args = argparser.parse_args()

    def init_logging(verbose=False):
        import logging
        global log
        log = logging.getLogger()
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(levelname)s: %(message)s')
        handler.setFormatter(formatter)
        log.addHandler(handler)
        if verbose:
            log.setLevel(logging.DEBUG)

    init_logging(args.verbose)
    log.debug('Program arguments: %s', args)

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
    if args.coverage:
        # TODO: https://coverage.readthedocs.org/en/coverage-4.0.2/api.html#api
        #       https://nose.readthedocs.org/en/latest/plugins/cover.html#source
        ...

    if args.x11:
        if not args.replay:
            error('--x11 requires --replay')
        # Escalate the power of shell
        import subprocess
        try:
            if 0 != subprocess.call(['xvfb-run', '--help'],
                                    stdout=subprocess.DEVNULL):
                raise OSError
        except OSError:
            error('Headless X11 (--x11) requires working xvfb-run. Install package xvfb.')
        log.info('Re-running head-less in Xvfb. '
                 # The following cannot be avoided because Xvfb writes all app's
                 # output, including stderr, to stdout
                 'All subprocess output (including stdout) will be piped to stderr.')
        sys.argv.remove('--x11')  # Prevent recursion
        from os import path
        REAL_EXIT(subprocess.call(
            ['xvfb-run',
             '--server-args', '-fbdir /tmp -screen 0 1280x1024x16',
             '--auth-file', path.join(path.expanduser('~'), '.Xauthority'),
             # Run in a new shell because multiple commands
             'sh', '-c',
             # Try to spawn a lightweight window manager
             ' '.join('{} 2>/dev/null &'.format(wm) for wm in WINDOW_MANAGERS) +
             ' sleep .5 ; ' +
             ' '.join(sys.argv)],
            stdout=sys.stderr))
    return args


PathElement = namedtuple('PathElement', ('index', 'type', 'name'))


class Resolver:
    FUZZY_MATCHING = False

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
        klass = klass or value.__class__

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
        klass = klass or value.__class__
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
            return 'QtCore.{}({}, {})'.format(value.__class__.__name__,
                                              value.x(),
                                              value.y())
        if isinstance(value, (QtCore.QRectF, QtCore.QRect)):
            return 'QtCore.{}({}, {})'.format(value.__class__.__name__,
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
        if value.__class__.__name__.endswith('s'):
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
    def serialize_event(cls, event):
        assert any('QEvent' == cls.__name__
                   for cls in event.__class__.__mro__), (event, event.__class__.__mro__)
        event_type = type(event)
        event_attributes = cls.EVENT_ATTRIBUTES.get(event_type.__name__, ('type',))
        if not event_attributes:
            log.warning('Unknown event: %s, type=%s, mro=%s',
                        event_type, event.type(), event_type.__mro__)

        args = [event_type.__name__]
        if event_attributes and event_attributes[0] == 'type':
            args.append('QtCore.' + cls._qenum_key(QtCore.QEvent, event.type()))
            # Skip first element (type) in the loop ahead
            event_attributes = iter(event_attributes); next(event_attributes)
        for attr in event_attributes:
            value = getattr(event, attr)()
            try: args.append(cls._serialize_value(value, attr))
            except ValueError:
                log.warning("Can't serialize object {} of type {} "
                            "for attribute {}".format(value,
                                                      value.__class__.__mro__,
                                                      attr))
        log.debug('Serialized event: %s', args)
        return tuple(args)

    @staticmethod
    def deserialize_event(event):
        if event[0] == 'QEvent':   # Generic, unspecialized QEvent
            assert len(event) == 2
            event = QtCore.QEvent(eval(event[1]))
            return event
        event = eval('QtGui.' + event[0] + '(' + ', '.join(event[1:]) + ')')
        return event

    @staticmethod
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
    def serialize_object(cls, obj):
        assert any('QObject' == cls.__name__
                   for cls in type(obj).mro()), (obj, type(obj).mro())

        def _canonical_path(obj):

            def _index_by_type(lst, obj):
                return [i for i in lst if type(i) == type(obj)].index(obj)

            if not obj.parent():
                pass
            parent = obj.parent()
            while parent is not None:
                yield obj, _index_by_type(parent.children(), obj)
                obj = parent
                parent = parent.parent()
            yield obj, _index_by_type(QtGui.qApp.topLevelWidgets(), obj)

        path = tuple(reversed([PathElement(index_by_type,
                                           cls.serialize_type(obj.__class__),
                                           obj.objectName())
                               for obj, index_by_type in _canonical_path(obj)]))
        log.debug('Serialized object path: %s', path)
        return path

    @classmethod
    def deserialize_object(cls, qApp, path):
        target = path[-1]
        target_type = cls.deserialize_type(target.type)

        # Find target object by name
        if target.name:
            obj = qApp.findChild(target_type, target.name)
            if obj:
                return obj

        # If target doesn't have a name, find the object in the tree
        # FIXME: The logic here may need rework

        def filtertype(target_type, iterable):
            return [i for i in iterable if type(i) == target_type]

        def get_candidates(widget, i):
            if not (type(widget) == path[i].type and
                    (not path[i].name or path[i].name == widget.objectName())):
                return

            if i == len(path) - 1:
                return widget

            # If fuzzy matching, all the children widgets are considered;
            # otherwise just the one in the correct position
            children = widget.children()
            if not cls.FUZZY_MATCHING:
                target = path[i + 1]
                try:
                    children = (filtertype(target_type, children)[target.index],)
                except IndexError:
                    # Insufficient children of correct type
                    return

            for child in children:
                obj = get_candidates(child, i + 1)
                if obj:
                    return obj

        target = path[0]
        widgets = qApp.topLevelWidgets()
        if not cls.FUZZY_MATCHING:
            try:
                widgets = (filtertype(target_type, widgets)[target.index],)
            except IndexError:
                return
        for window in widgets:
            obj = get_candidates(window, 0)
            if obj:
                return obj

        # No suitable object found
        return None

    @classmethod
    def getstate(cls, obj, event):
        """Return picklable state of the object and its event"""
        return (cls.serialize_object(obj),
                cls.serialize_event(event))

    @classmethod
    def setstate(cls, qApp, obj_path, event_str):
        obj = cls.deserialize_object(qApp, obj_path)
        if obj is None:
            log.error("Can't replay event %s on object %s: Object not found",
                      event_str, obj_path)
            REAL_EXIT(3)
        event = cls.deserialize_event(event_str)
        return qApp.sendEvent(obj, event)


def EventRecorder():
    """
    Return an instance of EventRecorder with closure over correct
    (PyQt4's or PyQt5's) version of QtCore.QObject.
    """
    global QtCore

    class EventRecorder(QtCore.QObject):

        QEVENT_EVENTS = {
            # Events that extend QEvent
            # QtCore.QEvent.Close,
            # QtCore.QEvent.ContextMenu,
            QtCore.QEvent.DragEnter,
            QtCore.QEvent.DragLeave,
            QtCore.QEvent.DragMove,
            QtCore.QEvent.Drop,
            QtCore.QEvent.Enter,
            # QtCore.QEvent.FocusIn,
            # QtCore.QEvent.FocusOut,
            QtCore.QEvent.KeyPress,
            QtCore.QEvent.KeyRelease,
            QtCore.QEvent.MouseButtonDblClick,
            QtCore.QEvent.MouseButtonPress,
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QEvent.MouseMove,
            QtCore.QEvent.Move,
            # QtCore.QEvent.Resize,
            QtCore.QStateMachine.SignalEvent,  # This doesn't work, forget about it
        }

        def __init__(self):
            super().__init__()
            self.events = [SCENARIO_VERSION]

        def eventFilter(self, obj, event):
            # Only process out-of-application, system (e.g. X11) events
            # if not event.spontaneous():
            #     return False
            if isinstance(event, QtCore.QStateMachine.SignalEvent):
                log.warning('Got signal event!')
            if event.type() == QtCore.QEvent.StateMachineSignal:
                log.warning('Got signal event!')
            is_skipped = event.type() not in self.QEVENT_EVENTS
            log.debug('Caught %s%s %s event: %s',
                      'spontaneous ' if event.spontaneous() else '',
                      'skipped' if is_skipped else 'recorded',
                      EVENT_TYPE.get(event.type(), 'Unknown(type=' + str(event.type()) + ')'),
                      type(event))
            if not is_skipped:
                self.events.append(Resolver.getstate(obj, event))
            return False

        def dump(self, file):
            log.debug('Writing scenario file')
            try: import cPickle as pickle
            except ImportError: import pickle
            pickle.dump(self.events, file, protocol=0)
            log.info("Scenario of %d events written into '%s'",
                     len(self.events) - SCENARIO_VERSION, file.name)

    return EventRecorder()


def EventReplayer():
    """
    Return an instance of EventReplayer with closure over correct
    (PyQt4's or PyQt5's) version of QtCore.
    """
    global QtCore, QtGui

    class EventReplayer(QtCore.QObject):

        started = False
        i = 0
        exitSuccessful = QtCore.pyqtSignal()

        def __init__(self):
            super().__init__()
            self.timer = timer = QtCore.QTimer(self)
            # Replay events X ms after the last event
            timer.setInterval(100)
            timer.timeout.connect(self.replay_next_event)

        def load(self, file):
            try: import cPickle as pickle
            except ImportError: import pickle
            self.events = iter(pickle.load(file))
            self.format_version = next(self.events)

        def eventFilter(self, obj, event):
            if not self.started:
                log.debug(
                    'Caught %s (%s) event but app not yet fully "started"',
                    EVENT_TYPE.get(event.type(), 'Unknown(type=' + str(event.type()) + ')'),
                    type(event).__name__)
                if event.type() == QtCore.QEvent.ActivationChange:
                    log.debug("Ok, app is started now, don't worry")
                    self.started = True
                # With the following return in place, Xvfb sometimes got stuck
                # before any serious events happened. I suspected WM (or lack
                # thereof) being the culprit, so now we spawn a WM that sends
                # focus, activation events, ... This seems to have fixed it once.
                # I think this return should be here.
                return False
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

        @QtCore.pyqtSlot()
        def replay_next_event(self):
            self.timer.stop()
            event = next(self.events, None)
            if not event:
                log.info('No more events to replay.')
                QtGui.qApp.quit()
                return
            log.debug('Replaying event: %s', event)
            Resolver.setstate(QtGui.qApp, *event)
            return False

    return EventReplayer()


def main():
    args = parse_args()

    # Set some global variables
    global QtGui, QtCore, Qt, QT_KEYS, EVENT_TYPE
    PyQt = 'PyQt' + str(args.qt)
    QtGui = import_module(PyQt + '.QtGui')
    QtCore = import_module(PyQt + '.QtCore')
    Qt = QtCore.Qt
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

    event_filters = []
    if args.record:
        recorder = EventRecorder()
        event_filters.append(recorder)
    if args.replay:
        replayer = EventReplayer()
        replayer.load(args.replay)
        event_filters.append(replayer)
    ...

    assert event_filters

    # Patch QApplication to filter all events through EventRecorder / EventReplayer
    class QApplication(QtGui.QApplication):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            for event_filter in event_filters:
                log.debug('Installing event filter: %s',
                          type(event_filter).__name__)
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

    return 0

if __name__ == '__main__':
    REAL_EXIT(main())
