## This shell script is run if program is run with --x11 option

# set -x  # Enable debugging
set -e

clean_up () {
    XAUTHORITY=$AUTH_FILE xauth remove :$DISPLAY >/dev/null 2>&1
    kill $(cat $XVFB_PID_FILE) >/dev/null 2>&1
}

trap clean_up EXIT

start_x11 () {
    # Appropriated from xvfb-run

    touch $AUTH_FILE
    XAUTHORITY=$AUTH_FILE $XAUTH add :$DISPLAY . $MCOOKIE

    # Handle SIGUSR1 so Xvfb knows to send a signal when ready. I don't really
    # understand how this was supposed to be handled by the code below, but
    # xvfb-run did it like this so ...

    trap : USR1
    (trap '' USR1;
     exec $XVFB :$DISPLAY -nolisten tcp  \
                          -auth $AUTH_FILE  \
                          -fbdir /tmp -screen 0 ${RESOLUTION}x16  \
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
    DISPLAY=:$DISPLAY XAUTHORITY=$AUTH_FILE sh -c "$ARGV"
    echo $? > $RETVAL_FILE
    set -e
}

start_ffmpeg () {
    [ "{VIDEO_FILE}" ] || return
    ffmpeg -y -nostats -hide_banner -loglevel fatal -r 25 \
           -f x11grab -s $RESOLUTION -i :$DISPLAY $VIDEO_FILE </dev/null &
    echo $! > $FFMPEG_PID_FILE
}

kill_ffmpeg () {
    [ "{VIDEO_FILE}" ] || return
    kill $(cat $FFMPEG_PID_FILE) 2>/dev/null
}

# WTF: For some reason variables don't retain values across functions ???
TMPDIR=${TMPDIR:-/tmp/}
FFMPEG_PID_FILE=$(mktemp $TMPDIR/pyqttester.ffmpeg.XXXXXXX)
XVFB_PID_FILE=$(mktemp $TMPDIR/pyqttester.xvfb.XXXXXXX)
RETVAL_FILE=$(mktemp $TMPDIR/pyqttester.retval.XXXXXXX)

# First start the Xvfb instance, replaying the scenario inside.
# Right afterwards, start screengrabbing the Xvfb session with ffmpeg.
# When the scenario completes, kill ffmpeg as well.

{ start_x11; kill_ffmpeg; } & start_ffmpeg ; wait

RETVAL=$(cat $RETVAL_FILE)
rm $FFMPEG_PID_FILE #RETVAL_FILE
exit $RETVAL
