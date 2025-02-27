# -*- coding: utf-8 -*-
#******************************************************************************
# ZYNTHIAN PROJECT: Zynthian Engine (zynthian_engine)
# 
# zynthian_engine is the base class for the Zynthian Synth Engine
# 
# Copyright (C) 2015-2016 Fernando Moyano <jofemodo@zynthian.org>
#
#******************************************************************************
# 
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of
# the License, or any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# For a full copy of the GNU General Public License see the LICENSE.txt file.
# 
#******************************************************************************

#import sys
import os
import re
import json
import liblo
import logging
import pexpect
from time import sleep
from string import Template
from collections import OrderedDict
from os.path import isfile, isdir, ismount, join

from . import zynthian_controller
from zyngui import zynthian_gui_config

#--------------------------------------------------------------------------------
# Basic Engine Class: Spawn a process & manage IPC communication using pexpect
#--------------------------------------------------------------------------------

class zynthian_basic_engine:

	# ---------------------------------------------------------------------------
	# Data dirs 
	# ---------------------------------------------------------------------------

	config_dir = os.environ.get('ZYNTHIAN_CONFIG_DIR', "/zynthian/config")
	data_dir = os.environ.get('ZYNTHIAN_DATA_DIR', "/zynthian/zynthian-data")
	my_data_dir = os.environ.get('ZYNTHIAN_MY_DATA_DIR', "/zynthian/zynthian-my-data")
	ex_data_dir = os.environ.get('ZYNTHIAN_EX_DATA_DIR', "/media/root")

	# ---------------------------------------------------------------------------
	# Initialization
	# ---------------------------------------------------------------------------

	def __init__(self, name=None, command=None, prompt=None, cwd=None):
		self.name = name
		self.layer_cb = None

		self.proc = None
		self.proc_timeout = 20
		self.proc_start_sleep = None
		self.command = command
		self.command_env = os.environ.copy()
		self.command_prompt = prompt
		self.command_cwd = cwd
		self.ignore_not_on_gui = False


	# ---------------------------------------------------------------------------
	# Subproccess Management & IPC
	# ---------------------------------------------------------------------------

	def start(self):
		if not self.proc:
			logging.info("Starting Engine {}".format(self.name))
			try:
				logging.debug("Command: {}".format(self.command))
				# Turns out that environment's PWD is not set automatically 
				# when cwd is specified for pexpect.spawn(), so do it here.
				if (self.command_cwd):
					self.command_env['PWD'] = self.command_cwd

				# Setting cwd is because we've set PWD above. Some engines doesn't
				# care about the process's cwd, but it is more consistent to set 
				# cwd when PWD has been set.
				self.proc = pexpect.spawn(self.command, timeout=self.proc_timeout, env=self.command_env, cwd=self.command_cwd)

				self.proc.delaybeforesend = 0

				output = self.proc_get_output()

				if self.proc_start_sleep:
					sleep(self.proc_start_sleep)

				return output

			except Exception as err:
				logging.error("Can't start engine {} => {}".format(self.name, err))


	def stop(self):
		if self.proc:
			try:
				logging.info("Stopping Engine " + self.name)
				self.proc.terminate()
				sleep(0.2)
				self.proc.terminate(True)
				self.proc = None
			except Exception as err:
				logging.error("Can't stop engine {} => {}".format(self.name, err))


	def proc_get_output(self):
		if self.command_prompt:
			self.proc.expect(self.command_prompt)
			return self.proc.before.decode()
		else:
			logging.warning("Command Prompt is not defined!")
			return None


	def proc_cmd(self, cmd):
		if self.proc:
			try:
				#logging.debug("proc command: "+cmd)
				self.proc.sendline(cmd)
				out=self.proc_get_output()
				#logging.debug("proc output:\n{}".format(out))
			except Exception as err:
				out=""
				logging.error("Can't exec engine command: {} => {}".format(cmd, err))
			return out


#------------------------------------------------------------------------------
# Synth Engine Base Class
#------------------------------------------------------------------------------

class zynthian_engine(zynthian_basic_engine):

	# ---------------------------------------------------------------------------
	# Default Controllers & Screens
	# ---------------------------------------------------------------------------

	# Standard MIDI Controllers
	_ctrls = []

	# Controller Screens
	_ctrl_screens = []

	# ---------------------------------------------------------------------------
	# Config variables
	# ---------------------------------------------------------------------------

	bank_dirs = None

	# ---------------------------------------------------------------------------
	# Initialization
	# ---------------------------------------------------------------------------

	def __init__(self, zyngui=None):
		super().__init__()

		self.zyngui = zyngui
		self.custom_gui_fpath = None

		self.type = "MIDI Synth"
		self.nickname = ""
		self.jackname = ""

		self.loading = 0
		self.layers = []

		self.options = {
			'clone': True,
			'note_range': True,
			'audio_capture': False,
			'audio_route': True,
			'midi_route': False,
			'midi_chan': True,
			'replace': True,
			'drop_pc': False,
			'drop_cc': True,
			'layer_audio_out': True
		}

		self.osc_proto = liblo.UDP
		self.osc_target = None
		self.osc_target_port = None
		self.osc_server = None
		self.osc_server_port = None
		self.osc_server_url = None

		self.preset_favs = None
		self.preset_favs_fpath = None
		self.show_favs_bank = True

		self.learned_cc = [[None for c in range(128)] for chan in range(16)]
		self.learned_zctrls = {}


	def reset(self):
		#Reset Vars
		self.loading=0
		self.loading_snapshot=False
		#TODO: OSC, IPC, ...


	def config_remote_display(self):
		if 'ZYNTHIAN_X11_SSH' in os.environ and 'SSH_CLIENT' in os.environ and 'DISPLAY' in os.environ:
			return True
		elif os.system('systemctl -q is-active vncserver1'):
			return False
		else:
			self.command_env['DISPLAY'] = ':1'
			return True


	def get_next_jackname(self, jname, sanitize=False):
		try:
			# Jack, when listing ports, accepts regular expressions as the jack name.
			# So, for avoiding problems, jack names shouldn't contain regex characters.
			if sanitize:
				jname = re.sub("[\_]{2,}", "_", re.sub("[\s\'\*\(\)\[\]]", "_", jname))
			jname = self.zyngui.screens['layer'].get_next_jackname(jname)
		except Exception as e:
			logging.error(e)
			return "{}-00".format(jname)
		return jname


	# ---------------------------------------------------------------------------
	# Loading GUI signalization
	# ---------------------------------------------------------------------------

	def start_loading(self):
		self.loading = self.loading + 1
		if self.loading < 1: self.loading = 1
		if self.zyngui:
			self.zyngui.start_loading()

	def stop_loading(self):
		self.loading = self.loading - 1
		if self.loading<0: self.loading = 0
		if self.zyngui:
			self.zyngui.stop_loading()

	def reset_loading(self):
		self.loading = 0
		if self.zyngui:
			self.zyngui.stop_loading()

	# ---------------------------------------------------------------------------
	# Refresh Management
	# ---------------------------------------------------------------------------

	def refresh_all(self, refresh=True):
		for layer in self.layers:
			layer.refresh_flag = refresh


	def refresh(self):
		raise NotImplementedError


	# ---------------------------------------------------------------------------
	# OSC Management
	# ---------------------------------------------------------------------------

	def osc_init(self):
		if self.osc_server is None and self.osc_target_port:
			try:
				self.osc_target = liblo.Address('localhost', self.osc_target_port, self.osc_proto)
				logging.info("OSC target in port {}".format(self.osc_target_port))
				self.osc_server = liblo.ServerThread(None, self.osc_proto, reg_methods=False)
				#self.osc_server = liblo.Server(None, self.osc_proto, reg_methods=False)
				self.osc_server_port = self.osc_server.get_port()
				self.osc_server_url = liblo.Address('localhost', self.osc_server_port, self.osc_proto).get_url()
				logging.info("OSC server running in port {}".format(self.osc_server_port))
				self.osc_add_methods()
				self.osc_server.start()
			except liblo.AddressError as err:
				logging.error("OSC Server can't be started ({}). Running without OSC feedback.".format(err))


	def osc_end(self):
		if self.osc_server:
			try:
				self.osc_server.stop()
				self.osc_server = None
				logging.info("OSC server stopped")
			except Exception as err:
				logging.error("OSC server can't be stopped => {}".format(err))


	def osc_add_methods(self):
		if self.osc_server:
			self.osc_server.add_method(None, None, self.cb_osc_all)


	def cb_osc_all(self, path, args, types, src):
		logging.info("OSC MESSAGE '{}' from '{}'".format(path, src.url))
		for a, t in zip(args, types):
			logging.debug("argument of type '{}': {}".format(t, a))


	# ---------------------------------------------------------------------------
	# Subproccess Management & IPC
	# ---------------------------------------------------------------------------

	def start(self):
		self.osc_init()
		super().start()


	def stop(self):
		super().stop()
		self.osc_end()

	# ---------------------------------------------------------------------------
	# Generating list from different sources
	# ---------------------------------------------------------------------------

	@staticmethod
	def get_filelist(dpath, fext):
		res = []
		if isinstance(dpath, str): dpath = [('_', dpath)]
		fext = '.' + fext
		xlen = len(fext)
		i = 0
		for dpd in dpath:
			dp = dpd[1]
			dn = dpd[0]
			try:
				for f in sorted(os.listdir(dp)):
					if not f.startswith('.') and isfile(join(dp, f)) and f[-xlen:].lower() == fext:
						title = str.replace(f[:-xlen], '_', ' ')
						if dn != '_': title = dn + '/' + title
						#print("filelist => " + title)
						res.append([join(dp, f), i, title, dn, f])
						i = i + 1
			except Exception as e:
				#logging.warning("Can't access directory '{}' => {}".format(dp,e))
				pass

		return res


	@staticmethod
	def get_dirlist(dpath, exclude_empty=True):
		res = []
		if isinstance(dpath, str):
			dpath = [('_', dpath)]
		i = 0
		for dpd in dpath:
			dp = dpd[1]
			dn = dpd[0]
			try:
				for f in sorted(os.listdir(dp)):
					dpath = join(dp,f)
					if not os.path.isdir(dpath) or (exclude_empty and next(os.scandir(dpath), None) is None):
						continue
					if not f.startswith('.') and isdir(dpath):
						title, ext = os.path.splitext(f)
						title = str.replace(title, '_', ' ')
						if dn != '_': title = dn + '/' + title
						res.append([dpath, i, title, dn, f])
						i = i + 1
			except Exception as e:
				#logging.warning("Can't access directory '{}' => {}".format(dp,e))
				pass

		return res

	# ---------------------------------------------------------------------------
	# Layer Management
	# ---------------------------------------------------------------------------

	def add_layer(self, layer):
		self.layers.append(layer)
		layer.jackname = self.jackname


	def del_layer(self, layer):
		self.layers.remove(layer)
		layer.jackname = None


	def del_all_layers(self):
		for layer in self.layers:
			self.del_layer(layer)


	def get_name(self, layer):
		return self.name


	def get_path(self, layer):
		return self.name

	# ---------------------------------------------------------------------------
	# MIDI Channel Management
	# ---------------------------------------------------------------------------

	def set_midi_chan(self, layer):
		pass


	def get_active_midi_channels(self):
		chans = []
		for layer in self.layers:
			if layer.midi_chan is None:
				return None
			elif layer.midi_chan >= 0 and layer.midi_chan <= 15:
				chans.append(layer.midi_chan)
		return chans


	# ---------------------------------------------------------------------------
	# Bank Management
	# ---------------------------------------------------------------------------

	def get_bank_dirs(self):
		if self.bank_dirs is not None:
			exdirs = zynthian_gui_config.get_external_storage_dirs(self.ex_data_dir)
			xbank_dirs = []
			for bd in self.bank_dirs:
				if bd[1].startswith(self.ex_data_dir):
					for exd in exdirs:
						xbank_dirs.append((bd[0], bd[1].replace(self.ex_data_dir, exd)))
				else:
					xbank_dirs.append(bd)
			return xbank_dirs
		else:
			return None


	def get_bank_list(self, layer=None):
		xbank_dirs = self.get_bank_dirs()
		if xbank_dirs is not None:
			return self.get_dirlist(xbank_dirs)
		else:
			logging.info('Getting Bank List for %s: NOT IMPLEMENTED!' % self.name)
			return []


	def set_bank(self, layer, bank):
		self.zyngui.zynmidi.set_midi_bank_msb(layer.get_midi_chan(), bank[1])
		return True


	# ---------------------------------------------------------------------------
	# Preset Management
	# ---------------------------------------------------------------------------

	def get_preset_list(self, bank):
		logging.info('Getting Preset List for %s: NOT IMPLEMENTED!', self.name)


	def set_preset(self, layer, preset, preload=False):
		if isinstance(preset[1], int):
			self.zyngui.zynmidi.set_midi_prg(layer.get_midi_chan(), preset[1])
		else:
			self.zyngui.zynmidi.set_midi_preset(layer.get_midi_chan(), preset[1][0], preset[1][1], preset[1][2])
		return True


	def cmp_presets(self, preset1, preset2):
		try:
			if preset1[1][0] == preset2[1][0] and preset1[1][1] == preset2[1][1] and preset1[1][2] == preset2[1][2]:
				return True
			else:
				return False
		except:
			return False


	def is_preset_user(self, preset):
		return isinstance(preset[0], str) and preset[0].startswith(self.my_data_dir)


	def preset_exists(self, bank_info, preset_name):
		logging.error("Not implemented!!!")


	# Implement in derived classes to enable features in GUI
	#def save_preset(self, bank_name, preset_name):
	#def delete_preset(self, bank_info, preset):
	#def rename_preset(self, bank_info, preset, new_name):

	# ---------------------------------------------------------------------------
	# Preset Favorites Management
	# ---------------------------------------------------------------------------

	def toggle_preset_fav(self, layer, preset):
		if self.preset_favs is None:
			self.load_preset_favs()

		try:
			del self.preset_favs[str(preset[0])]
			fav_status = False
		except:
			self.preset_favs[str(preset[0])] = [layer.bank_info, preset]
			fav_status = True

		try:
			with open(self.preset_favs_fpath, 'w') as f:
				json.dump(self.preset_favs, f)
		except Exception as e:
			logging.error("Can't save preset favorites! => {}".format(e))

		return fav_status


	def remove_preset_fav(self, preset):
		if self.preset_favs is None:
			self.load_preset_favs()
		try:
			del self.preset_favs[str(preset[0])]
			with open(self.preset_favs_fpath, 'w') as f:
				json.dump(self.preset_favs, f)
		except:
			pass # Don't care if preset not in favs


	def get_preset_favs(self, layer):
		if self.preset_favs is None:
			self.load_preset_favs()

		return self.preset_favs


	def is_preset_fav(self, preset):
		if self.preset_favs is None:
			self.load_preset_favs()

		#if str(preset[0]) in [str(item[1][0]) for item in self.preset_favs.values()]:
		if str(preset[0]) in self.preset_favs:
			return True
		else:
			return False


	def load_preset_favs(self):
		if self.nickname:
			fname = self.nickname.replace("/","_")
			self.preset_favs_fpath = self.my_data_dir + "/preset-favorites/" + fname + ".json"

			try:
				with open(self.preset_favs_fpath) as f:
					self.preset_favs = json.load(f, object_pairs_hook=OrderedDict)
			except:
				self.preset_favs = OrderedDict()

			#TODO: Remove invalid presets from favourite's list

		else:
			logging.warning("Can't load preset favorites until the engine have a nickname!")


	# ---------------------------------------------------------------------------
	# Controllers Management
	# ---------------------------------------------------------------------------

	def set_ctrl_update_cb(self, cb):
		self.layer_cb = cb


	# Get zynthian controllers dictionary:
	# + Default implementation uses a static controller definition array
	def get_controllers_dict(self, layer):
		midich = layer.get_midi_chan()
		zctrls = OrderedDict()

		if self._ctrls is not None:
			for ctrl in self._ctrls:
				options = {}

				#OSC control =>
				if isinstance(ctrl[1], str):
					#replace variables ...
					tpl = Template(ctrl[1])
					cc = tpl.safe_substitute(ch = midich)
					try:
						cc = tpl.safe_substitute(i = layer.part_i)
					except:
						pass
					#set osc_port option ...
					if self.osc_target_port > 0:
						options['osc_port'] = self.osc_target_port
					#debug message
					logging.debug('CONTROLLER %s OSC PATH => %s' % (ctrl[0],cc))
				#MIDI Control =>
				else:
					cc = ctrl[1]

				#Build controller depending on array length ...
				if len(ctrl) > 4:
					if isinstance(ctrl[4], str):
						zctrl = zynthian_controller(self, ctrl[4], ctrl[0])
					else:
						zctrl = zynthian_controller(self, ctrl[0])
						zctrl.graph_path = ctrl[4]
					zctrl.setup_controller(midich, cc, ctrl[2], ctrl[3])
				elif len(ctrl) > 3:
					zctrl = zynthian_controller(self, ctrl[0])
					zctrl.setup_controller(midich, cc, ctrl[2], ctrl[3])
				else:
					zctrl = zynthian_controller(self, ctrl[0])
					zctrl.setup_controller(midich, cc, ctrl[2])

				#Set controller extra options
				if len(options) > 0:
					zctrl.set_options(options)

				zctrls[zctrl.symbol] = zctrl
		return zctrls


	def get_ctrl_screen_name(self, gname, i):
		if i > 0:
			gname = "{}#{}".format(gname, i)
		return gname


	def generate_ctrl_screens(self, zctrl_dict):
		if self._ctrl_screens is None:
			self._ctrl_screens = []

		# Get zctrls by group
		zctrl_group = OrderedDict()
		for symbol, zctrl in zctrl_dict.items():
			gsymbol = zctrl.group_symbol
			if gsymbol not in zctrl_group:
				if zctrl.group_name:
					zctrl_group[gsymbol] = [zctrl.group_name, OrderedDict()]
				else:
					zctrl_group[gsymbol] = [zctrl.group_symbol, OrderedDict()]
			zctrl_group[gsymbol][1][symbol] = zctrl
		if None in zctrl_group:
			zctrl_group[None][0] = "Ctrls"

		for gsymbol, gdata in zctrl_group.items():
			ctrl_set = []
			gname = gdata[0]
			if len(gdata[1]) <= 4:
				c = 0
			else:
				c = 1
			for symbol, zctrl in gdata[1].items():
				try:
					if not self.ignore_not_on_gui and zctrl.not_on_gui:
						continue
					#logging.debug("CTRL {}".format(symbol))
					ctrl_set.append(symbol)
					if len(ctrl_set) >= 4:
						#logging.debug("ADDING CONTROLLER SCREEN {}".format(self.get_ctrl_screen_name(gname,c)))
						self._ctrl_screens.append([self.get_ctrl_screen_name(gname,c),ctrl_set])
						ctrl_set = []
						c = c + 1
				except Exception as err:
					logging.error("Generating Controller Screens => {}".format(err))

			if len(ctrl_set) >= 1:
				#logging.debug("ADDING CONTROLLER SCREEN {}",format(self.get_ctrl_screen_name(gname,c)))
				self._ctrl_screens.append([self.get_ctrl_screen_name(gname,c),ctrl_set])


	def send_controller_value(self, zctrl):
		raise Exception("NOT IMPLEMENTED!")


	#----------------------------------------------------------------------------
	# MIDI learning
	#----------------------------------------------------------------------------

	def init_midi_learn(self, zctrl):
		logging.info("Learning '{}' ({}) ...".format(zctrl.symbol, zctrl.get_path()))


	def midi_unlearn(self, zctrl):
		if zctrl.get_path() in self.learned_zctrls:
			#logging.info("Unlearning '{}' ...".format(zctrl.symbol))
			try:
				self.learned_cc[zctrl.midi_learn_chan][zctrl.midi_learn_cc] = None
				del self.learned_zctrls[zctrl.get_path()]
				return zctrl._unset_midi_learn()
			except Exception as e:
				logging.warning("Can't unlearn => {}".format(e))


	def set_midi_learn(self, zctrl, chan, cc):
		try:
			# Clean implied CC bindings if any ...
			try:
				self.learned_cc[chan][cc].midi_unlearn()
			except:
				pass
			try:
				self.midi_unlearn(zctrl)
			except:
				pass

			# Add midi learning info
			self.learned_zctrls[zctrl.get_path()] = zctrl
			self.learned_cc[chan][cc] = zctrl
			return zctrl._set_midi_learn(chan, cc)
		except Exception as e:
			logging.error("Can't learn {} ({}) for CH{}#CC{} => {}".format(zctrl.symbol, zctrl.get_path(), chan, cc, e))


	def keep_midi_learn(self, zctrl):
		try:
			zpath = zctrl.get_path()
			old_zctrl = self.learned_zctrls[zpath]
			chan = old_zctrl.midi_learn_chan
			cc = old_zctrl.midi_learn_cc
			self.learned_zctrls[zpath] = zctrl
			self.learned_cc[chan][cc] = zctrl
			return zctrl._set_midi_learn(chan, cc)
		except:
			pass


	def refresh_midi_learn(self):
		logging.info("Refresh MIDI-learn ...")
		self.learned_cc = [[None for c in range(128)] for chan in range(16)]
		for zctrl in self.learned_zctrls.values():
			self.learned_cc[zctrl.midi_learn_chan][zctrl.midi_learn_cc] = zctrl


	def reset_midi_learn(self):
		logging.info("Reset MIDI-learn ...")
		self.learned_zctrls = {}
		self.learned_cc = [[None for c in range(128)] for chan in range(16)]


	def cb_midi_learn(self, zctrl, chan, cc):
		return self.set_midi_learn(zctrl, chan, cc)


	#----------------------------------------------------------------------------
	# MIDI CC processing
	#----------------------------------------------------------------------------

	def midi_control_change(self, chan, ccnum, val):
		if self.learned_cc[chan][ccnum]:
			self.learned_cc[chan][ccnum].midi_control_change(val)


	def midi_zctrl_change(self, zctrl, val):
		if val != zctrl.get_ctrl_midi_val():
			try:
				zctrl.midi_control_change(val)
			except Exception as e:
				logging.debug(e)


	# ---------------------------------------------------------------------------
	# Options and Extended Config
	# ---------------------------------------------------------------------------

	def get_options(self):
		return self.options


	def get_extended_config(self):
		return None


	def set_extended_config(self, xconfig):
		pass

	# ---------------------------------------------------------------------------
	# API methods
	# ---------------------------------------------------------------------------

	@classmethod
	def get_zynapi_methods(cls):
		return [f for f in dir(cls) if f.startswith('zynapi_')]
		#callable(f) and


	# Remove double spacing
	@classmethod
	def remove_double_spacing(cls, lines):
		double_line = []
		for index,line in enumerate(lines):
			if line.strip() == "" and index > 0 and lines[index - 1].strip() == "":
				double_line.append(index)
		double_line.sort(reverse=True)
		for line in double_line:
			del lines[line]


#******************************************************************************
