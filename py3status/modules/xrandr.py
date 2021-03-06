# -*- coding: utf-8 -*-
"""
Control your screen(s) layout easily.

This modules allows you to handle your screens outputs directly from your bar!
    - Detect and propose every possible screen combinations
    - Switch between combinations using click events and mouse scroll
    - Activate the screen or screen combination on a single click
    - It will detect any newly connected or removed screen automatically

For convenience, this module also proposes some added features:
    - Dynamic parameters for POSITION and WORKSPACES assignment (see below)
    - Automatic fallback to a given screen or screen combination when no more
        screen is available (handy for laptops)
    - Automatically apply this screen combination on start: no need for xorg!
    - Automatically move workspaces to screens when they are available

Configuration parameters:
    - cache_timeout: how often to (re)detect the outputs
    - fallback: when the current output layout is not available anymore,
        fallback to this layout if available. This is very handy if you
        have a laptop and switched to an external screen for presentation
        and want to automatically fallback to your laptop screen when you
        disconnect the external screen.
    - force_on_start: switch to the given combination mode if available
        when the module starts (saves you from having to configure xorg)
    - format_clone: string used to display a 'clone' combination
    - format_extend: string used to display a 'extend' combination

Dynamic configuration parameters:
    - <OUTPUT>_pos: apply the given position to the OUTPUT
        Example: DP1_pos = "-2560x0"
        Example: DP1_pos = "above eDP1"
        Example: DP1_pos = "below eDP1"
        Example: DP1_pos = "left-of LVDS1"
        Example: DP1_pos = "right-of eDP1"

    - <OUTPUT>_workspaces: comma separated list of workspaces to move to
        the given OUTPUT when it is activated
        Example: DP1_workspaces = "1,2,3"

Example config:
    xrandr {
        force_on_start = "eDP1+DP1"
        DP1_pos = "left-of eDP1"
        VGA_workspaces = "7"
    }

@author ultrabug
"""
import shlex

from collections import deque
from collections import OrderedDict
from itertools import combinations
from subprocess import call, Popen, PIPE
from syslog import syslog, LOG_INFO
from time import sleep, time


class Py3status:
    """
    """
    # available configuration parameters
    cache_timeout = 10
    fallback = True
    fixed_width = True
    force_on_start = None
    format_clone = '='
    format_extend = '+'

    def __init__(self):
        """
        """
        self.active_comb = None
        self.active_layout = None
        self.active_mode = 'extend'
        self.displayed = None
        self.max_width = 0

    def _get_layout(self):
        """
        Get the outputs layout from xrandr and try to detect the
        currently active layout as best as we can on start.
        """
        connected = list()
        active_layout = list()
        disconnected = list()
        layout = OrderedDict(
            {
                'connected': OrderedDict(),
                'disconnected': OrderedDict()
            }
        )

        current = Popen(['xrandr'], stdout=PIPE)
        for line in current.stdout.readlines():
            try:
                # python3
                line = line.decode()
            except:
                pass
            try:
                s = line.split(' ')
                if s[1] == 'connected':
                    output, state = s[0], s[1]
                    if s[2][0] == '(':
                        mode, infos = None, ' '.join(s[2:]).strip('\n')
                    else:
                        mode, infos = s[2], ' '.join(s[3:]).strip('\n')
                        active_layout.append(output)
                    connected.append(output)
                elif s[1] == 'disconnected':
                    output, state = s[0], s[1]
                    mode, infos = None, ' '.join(s[2:]).strip('\n')
                    disconnected.append(output)
                else:
                    continue
            except Exception as err:
                syslog(LOG_INFO, 'xrandr error="{}"'.format(err))
            else:
                layout[state][output] = {
                    'infos': infos,
                    'mode': mode,
                    'state': state
                }

        # initialize the active layout
        if self.active_layout is None:
            self.active_comb = tuple(active_layout)
            self.active_layout = self._get_string_and_set_width(
                tuple(active_layout),
                self.active_mode
            )

        return layout

    def _set_available_combinations(self):
        """
        Generate all connected outputs combinations and
        set the max display width while iterating.
        """
        available_combinations = set()
        combinations_map = {}

        self.max_width = 0
        for output in range(len(self.layout['connected'])+1):
            for comb in combinations(self.layout['connected'], output):
                if comb:
                    for mode in ['clone', 'extend']:
                        string = self._get_string_and_set_width(comb, mode)
                        if len(comb) == 1:
                            combinations_map[string] = (comb, None)
                        else:
                            combinations_map[string] = (comb, mode)
                        available_combinations.add(string)
        self.available_combinations = deque(available_combinations)
        self.combinations_map = combinations_map

    def _get_string_and_set_width(self, combination, mode):
        """
        Construct the string to be displayed and record the max width.
        """
        show = '{}'.format(self._separator(mode)).join(combination)
        show = show.rstrip('{}'.format(self._separator(mode)))
        self.max_width = max([self.max_width, len(show)])
        return show

    def _choose_what_to_display(self, force_refresh=False):
        """
        Choose what combination to display on the bar.

        By default we try to display the active layout on the first run, else
        we display the last selected combination.
        """
        for _ in range(len(self.available_combinations)):
            if (
                self.displayed is None and
                self.available_combinations[0] == self.active_layout
            ):
                self.displayed = self.available_combinations[0]
                break
            else:
                if self.displayed == self.available_combinations[0]:
                    break
                else:
                    self.available_combinations.rotate(1)
        else:
            if force_refresh:
                self.displayed = self.available_combinations[0]
            else:
                syslog(
                    LOG_INFO,
                    'xrandr error="displayed combination is not available"'
                )

    def _center(self, s):
        """
        Center the given string on the detected max width.
        """
        fmt = '{:^%d}' % self.max_width
        return fmt.format(s)

    def _apply(self, force=False):
        """
        Call xrandr and apply the selected (displayed) combination mode.
        """
        if self.displayed == self.active_layout and not force:
            # no change, do nothing
            return

        combination, mode = self.combinations_map.get(
            self.displayed, (None, None)
        )
        if combination is None and mode is None:
            # displayed combination cannot be activated, ignore
            return

        cmd = 'xrandr'
        outputs = list(self.layout['connected'].keys())
        outputs += list(self.layout['disconnected'].keys())
        previous_output = None
        for output in outputs:
            cmd += ' --output {}'.format(output)
            #
            if output in combination:
                pos = getattr(self, '{}_pos'.format(output), '0x0')
                #
                if mode == 'clone' and previous_output is not None:
                    cmd += ' --auto --same-as {}'.format(previous_output)
                else:
                    if (
                        'above' in pos or
                        'below' in pos or
                        'left-of' in pos or
                        'right-of' in pos
                    ):
                        cmd += ' --auto --{} --rotate normal'.format(pos)
                    else:
                        cmd += ' --auto --pos {} --rotate normal'.format(pos)
                previous_output = output
            else:
                cmd += ' --off'
        #
        code = call(shlex.split(cmd))
        if code == 0:
            self.active_comb = combination
            self.active_layout = self.displayed
            self.active_mode = mode
        syslog(LOG_INFO, 'command "{}" exit code {}'.format(cmd, code))

        # move workspaces to outputs as configured
        self._apply_workspaces(combination, mode)

    def _apply_workspaces(self, combination, mode):
        """
        Allows user to force move a comma separated list of workspaces to the
        given output when it's activated.

        Example:
            - DP1_workspaces = "1,2,3"
        """
        if len(combination) > 1 and mode == 'extend':
            sleep(3)
            for output in combination:
                workspaces = getattr(
                    self, '{}_workspaces'.format(output), '').split(',')
                for workspace in workspaces:
                    if not workspace:
                        continue
                    # switch to workspace
                    cmd = 'i3-msg workspace "{}"'.format(workspace)
                    call(shlex.split(cmd), stdout=PIPE, stderr=PIPE)
                    # move it to output
                    cmd = 'i3-msg move workspace to output "{}"'.format(output)
                    call(shlex.split(cmd), stdout=PIPE, stderr=PIPE)
                    # log this
                    syslog(
                        LOG_INFO,
                        'moved workspace {} to output {}'.format(
                            workspace, output)
                    )

    def _refresh_py3status(self):
        """
        Send a SIGUSR1 signal to py3status to force a bar refresh.
        """
        call(shlex.split('killall -s USR1 py3status'))

    def _fallback_to_available_output(self):
        """
        Fallback to the first available output when the active layout
        was composed of only one output.

        This allows us to avoid cases where you get stuck with a black sreen
        on your laptop by switching back to the integrated screen
        automatically !
        """
        if len(self.active_comb) == 1:
            self._choose_what_to_display(force_refresh=True)
            self._apply()
            self._refresh_py3status()

    def _force_force_on_start(self):
        """
        Force the user configured mode on start.
        """
        if self.force_on_start in self.available_combinations:
            self.displayed = self.force_on_start
            self.force_on_start = None
            self._choose_what_to_display(force_refresh=True)
            self._apply(force=True)
            self._refresh_py3status()

    def _separator(self, mode):
        """
        Return the separator for the given mode.
        """
        if mode == 'extend':
            return self.format_extend
        if mode == 'clone':
            return self.format_clone

    def _switch_selection(self, direction):
        self.available_combinations.rotate(direction)
        self.displayed = self.available_combinations[0]

    def on_click(self, i3s_output_list, i3s_config, event):
        """
        Click events
            - left click & scroll up/down: switch between modes
            - right click: apply selected mode
            - middle click: force refresh of available modes
        """
        button = event['button']
        if button == 4:
            self._switch_selection(-1)
        if button in [1, 5]:
            self._switch_selection(1)
        if button == 2:
            self._choose_what_to_display(force_refresh=True)
        if button == 3:
            self._apply()

    def xrandr(self, i3s_output_list, i3s_config):
        """
        This is the main py3status method, it will orchestrate what's being
        displayed on the bar.
        """
        self.layout = self._get_layout()
        self._set_available_combinations()
        self._choose_what_to_display()

        if self.fixed_width is True:
            full_text = self._center(self.displayed)
        else:
            full_text = self.displayed

        response = {
            'cached_until': time() + self.cache_timeout,
            'full_text': full_text
        }

        # coloration
        if self.displayed == self.active_layout:
            response['color'] = i3s_config['color_good']
        elif self.displayed not in self.available_combinations:
            response['color'] = i3s_config['color_bad']

        # force default layout setup
        if self.force_on_start is not None:
            sleep(1)
            self._force_force_on_start()

        # fallback detection
        if self.active_layout not in self.available_combinations:
            response['color'] = i3s_config['color_degraded']
            if self.fallback is True:
                self._fallback_to_available_output()

        return response

if __name__ == "__main__":
    """
    Test this module by calling it directly.
    """
    x = Py3status()
    config = {
        'color_bad': '#FF0000',
        'color_degraded': '#FFFF00',
        'color_good': '#00FF00'
    }
    while True:
        print(x.xrandr([], config))
        sleep(1)
