#!/usr/bin/env python3

import sys
from importlib import import_module

try:
    import cPickle as pickle
except ImportError:
    import pickle


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


def parse_args():
    from argparse import ArgumentParser
    argparser = ArgumentParser()
    argparser.add_argument('--verbose', '-v', action='store_true',
                           help='')
    argparser.add_argument('--qt', metavar='QT_VERSION', default='4',
                           help='')
    group = argparser.add_mutually_exclusive_group(required=True)
    group.add_argument('--record', metavar='FILE',
                       help='')
    group.add_argument('--playback', metavar='FILE',
                       help='')
    argparser.add_argument('--entry-point', '-m', metavar='MODULE_PATH',
                           help='')
    argparser.add_argument('--fuzzy', action='store_true',
                           help='fuzzy-matching of event target widgets, e.g.')
    args = argparser.parse_args()
    init_logging(args.verbose)

    try:
        if args.record:
            try:
                module, entry = args.entry_point.rsplit('.', 1)
                module = import_module(module)
                entry = getattr(module, entry)
                if not callable(entry): raise Exception
            except Exception as e:
                log.error('--entry-point ("module.path.to.main_function") '
                          'required when --record: {}'.format(e))
                raise
            else:
                args.entry_point = entry

            try: args.record = open(args.record, 'w')
            except Exception as e:
                log.error('--record: {}'.format(e))
                raise
        if args.playback:
            try: args.playback = open(args.playback)
            except Exception as e:
                log.error('--playback: {}'.format(e))
                raise
    except Exception:
        sys.exit(1)
    return args


def main():
    args = parse_args()

    PyQt = 'PyQt' + str(args.qt)
    QtGui = import_module(PyQt + '.QtGui')
    QtCore = import_module(PyQt + '.QtCore')

    if args.record:

        class EventRecorder(QtCore.QObject):

            RECORD_EVENTS = {
                QtCore.QEvent.Close,
                QtCore.QEvent.ContextMenu,
                QtCore.QEvent.DragEnter,
                QtCore.QEvent.DragLeave,
                QtCore.QEvent.DragMove,
                QtCore.QEvent.Drop,
                QtCore.QEvent.Enter,
                QtCore.QEvent.FocusIn,
                QtCore.QEvent.FocusOut,
                QtCore.QEvent.KeyPress,
                QtCore.QEvent.KeyRelease,
                QtCore.QEvent.MouseButtonDblClick,
                QtCore.QEvent.MouseButtonPress,
                QtCore.QEvent.MouseButtonRelease,
                QtCore.QEvent.MouseMove,
                QtCore.QEvent.Move,
                QtCore.QEvent.Resize,
            }

            def __init__(self, args):
                super(self.__class__, self).__init__()
                self.file = args.record
                self.EventType = {v: k
                                  for k, v in QtCore.QEvent.__dict__.items()
                                  if isinstance(v, int)}

            def eventFilter(self, obj, event):
                self.recordEvent(obj, event)
                return False

            def recordEvent(self, obj, event):
                # If event isn't a system (out-of-application-originated) event
                if not event.spontaneous(): return

                if event.type() not in self.RECORD_EVENTS:
                    log.debug('Caught {} event which is skipped'.format(self.EventType[event.type()]))
                    return

                print(obj, self.EventType[event.type()])

            def writeout(self):
                pickle.dump(self.log, self.file, protocol=pickle.HIGHEST_PROTOCOL)


        event_filter = EventRecorder(args)

        # Patch QApplication to filter all events through EventRecorder
        QApplication=QtGui.QApplication

        def eventfilterQApplication(*args, **kwargs):
            app = QApplication(*args, **kwargs)
            app.installEventFilter(event_filter)
            return app

        QtGui.QApplication = eventfilterQApplication

        # Execute the app
        log.info('Running {}.{}'.format(args.entry_point.__module__,
                                        args.entry_point.__name__))
        args.entry_point()

        # Write the "logs"
        event_filter.writeout()





    elif args.playback:
        pass
    else: pass

    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main())
