#!/bin/sh
# Routes the DAC to the tablet's built-in speakers and saves the mixer state, so the
# clock's timer alarm is audible. Run once on the device: sh system/speaker-on.sh
# The alarm sets its own loudness ("clock.volume" in config.json) each time it rings.
# The state from before the first run is kept in ~/asound.state.before-speaker.
set -e
CARD=WM8962
VOLUME=${1:-80%}

set_ctl() { amixer -q -c "$CARD" cset name="$1" "$2"; }

set_ctl 'SPKOUTL PGA' DAC          # the DAC feeds the speaker amp directly, not via the mixer
set_ctl 'SPKOUTR PGA' DAC
set_ctl 'Speaker Switch' on,on
set_ctl 'Speaker Volume' "$VOLUME"
set_ctl 'Int Spk Switch' on
set_ctl 'Speakers Switch' on
set_ctl 'Digital Playback Volume' 96,96   # 0 dB, the driver default

sudo alsactl store
