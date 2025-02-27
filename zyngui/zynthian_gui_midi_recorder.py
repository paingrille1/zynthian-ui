#!/usr/bin/python3
# -*- coding: utf-8 -*-
#******************************************************************************
# ZYNTHIAN PROJECT: Zynthian GUI
# 
# Zynthian GUI MIDI Recorder Class
# 
# Copyright (C) 2015-2022 Fernando Moyano <jofemodo@zynthian.org>
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

import os
import logging
from threading import Timer
from time import sleep
from os.path import isfile, join, basename
import ctypes
import tkinter

# Zynthian specific modules
import zynconf
from zyngui import zynthian_gui_config
from zyngui.zynthian_gui_selector import zynthian_gui_selector
from zyngui.zynthian_gui_controller import zynthian_gui_controller
from zynlibs.zynsmf import zynsmf # Python wrapper for zynsmf (ensures initialised and wraps load() function)
from zynlibs.zynsmf.zynsmf import libsmf # Direct access to shared library 

#------------------------------------------------------------------------------
# Zynthian MIDI Recorder GUI Class
#------------------------------------------------------------------------------

class zynthian_gui_midi_recorder(zynthian_gui_selector):

	def __init__(self):
		self.capture_dir_sdc = os.environ.get('ZYNTHIAN_MY_DATA_DIR', "/zynthian/zynthian-my-data") + "/capture"
		self.ex_data_dir = os.environ.get('ZYNTHIAN_EX_DATA_DIR', "/media/root")

		self.current_playback_fpath = None # Filename of currently playing SMF

		self.smf_player = None # Pointer to SMF player
		self.smf_recorder = None # Pointer to SMF recorder
		self.smf_timer = None # 1s timer used to check end of SMF playback

		super().__init__('MIDI Recorder', True)

		self.bpm_zgui_ctrl = None

		try:
			self.smf_player = libsmf.addSmf()
			libsmf.attachPlayer(self.smf_player)
		except Exception as e:
			logging.error(e)

		try:
			self.smf_recorder = libsmf.addSmf()
			libsmf.attachRecorder(self.smf_recorder)
		except Exception as e:
			logging.error(e)

		logging.info("midi recorder created")


	def check_playback(self):
		if libsmf.getPlayState() == 0:
			self.end_playing()
		else:
			self.smf_timer = Timer(interval = 1, function=self.check_playback)
			self.smf_timer.start()


	def get_status(self):
		status = None

		if libsmf.isRecording():
			status = "REC"

		if libsmf.getPlayState():
			if status == "REC":
				status = "PLAY+REC"
			else:
				status = "PLAY"

		return status


	def build_view(self):
		super().build_view()
		if zynthian_gui_config.transport_clock_source == 0 and libsmf.getPlayState():
			self.show_playing_bpm()


	def hide(self):
		self.hide_playing_bpm()
		super().hide()


	def fill_list(self):
		#self.index = 0
		self.list_data = []

		self.list_data.append(None)
		self.update_status_recording()

		self.list_data.append(None)
		self.update_status_loop()

		self.list_data.append((None, 0, "> MIDI Tracks"))

		# Generate file list, sorted by mtime
		flist = self.get_filelist(self.capture_dir_sdc, "SD")
		for exd in zynthian_gui_config.get_external_storage_dirs(self.ex_data_dir):
			flist += self.get_filelist(exd, "USB")
		i = 1
		for finfo in sorted(flist, key=lambda d: d['mtime'], reverse=True) :
			self.list_data.append((finfo['fpath'], i, finfo['title']))
			i += 1

		super().fill_list()


	def get_filelist(self, src_dir, src_name):
		res = []
		smf = libsmf.addSmf()

		for f in os.listdir(src_dir):
			fpath = join(src_dir, f)
			fname = f[:-4]
			fext = f[-4:].lower()
			if isfile(fpath) and fext in ('.mid'):
				# Get mtime
				mtime = os.path.getmtime(fpath)

				# Get duration
				try:
					zynsmf.load(smf, fpath)
					length = libsmf.getDuration(smf)
				except Exception as e:
					length = 0
					logging.warning(e)

				# Generate title
				title = "{}[{}:{:02d}] {}".format(src_name, int(length/60), int(length % 60), fname.replace(";", ">", 1).replace(";", "/"))

				res.append({
					'fpath': fpath,
					'fname': fname,
					'ext': fext,
					'length': length,
					'mtime': mtime,
					'title': title
				})

		libsmf.removeSmf(smf)
		return res


	def fill_listbox(self):
		super().fill_listbox()
		self.update_status_playback()


	def update_status_playback(self):
		if libsmf.getPlayState() == 0:
			self.current_playback_fpath = None

		item_labels = self.listbox.get(0, tkinter.END)
		for i, row in enumerate(self.list_data):
			if row[0] and row[0] == self.current_playback_fpath:
				item_label = '▶ ' + row[2]
			else:
				item_label = row[2]

			if item_labels[i] != item_label:
				self.listbox.delete(i)
				self.listbox.insert(i, item_label)

		self.select_listbox(self.index)


	def update_status_recording(self, fill=False):
		if self.list_data:
			if libsmf.isRecording():
				self.list_data[0] = ("STOP_RECORDING", 0, "■ Stop MIDI Recording")
			else:
				self.list_data[0] = ("START_RECORDING", 0, "⬤ Start MIDI Recording")
			if fill:
				self.listbox.delete(0)
				self.listbox.insert(0, self.list_data[0][2])
				self.select_listbox(self.index)


	def update_status_loop(self, fill=False):
		if zynthian_gui_config.midi_play_loop:
			self.list_data[1] = ("LOOP", 0, "[x] Loop Play")
			libsmf.setLoop(True)
		else:
			self.list_data[1] = ("LOOP", 0, "[  ] Loop Play")
			libsmf.setLoop(False)
		if fill:
			self.listbox.delete(1)
			self.listbox.insert(1, self.list_data[1][2])
			self.select_listbox(self.index)


	def select_action(self, i, t='S'):
		fpath = self.list_data[i][0]

		if fpath == "START_RECORDING":
			self.start_recording()
		elif fpath == "STOP_PLAYING":
			self.stop_playing()
		elif fpath == "STOP_RECORDING":
			self.stop_recording()
		elif fpath == "LOOP":
			self.toggle_loop()
		elif fpath:
			if t == 'S':
				self.toggle_playing(fpath)
			else:
				self.zyngui.show_confirm("Do you really want to delete '{}'?".format(self.list_data[i][2]), self.delete_confirmed, fpath)


	# Function to handle *all* switch presses.
	#	swi: Switch index [0=Layer, 1=Back, 2=Snapshot, 3=Select]
	#	t: Press type ["S"=Short, "B"=Bold, "L"=Long]
	#	returns True if action fully handled or False if parent action should be triggered
	def switch(self, swi, t='S'):
		if swi == 0:
			if t == 'S':
				return True


	def get_next_filenum(self):
		try:
			n = max(map(lambda item: int(os.path.basename(item[0])[0:3]) if item[0] and os.path.basename(item[0])[0:3].isdigit() else 0, self.list_data))
		except:
			n = 0
		return "{0:03d}".format(n+1)


	def get_new_filename(self):
		try:
			parts = self.zyngui.curlayer.get_presetpath().split('#',2)
			file_name = parts[1].replace("/", ";").replace(">", ";").replace(" ; ", ";")
		except:
			file_name = "jack_capture"
		return self.get_next_filenum() + '-' + file_name + '.mid'


	def delete_confirmed(self, fpath):
		logging.info("DELETE MIDI RECORDING: {}".format(fpath))
		try:
			os.remove(fpath)
			self.fill_list()
		except Exception as e:
			logging.error(e)


	def start_recording(self):
		if not libsmf.isRecording():
			logging.info("STARTING NEW MIDI RECORD ...")
			libsmf.unload(self.smf_recorder)
			libsmf.startRecording()
			self.update_status_recording(True)
			return True
		else:
			return False


	def stop_recording(self):
		if libsmf.isRecording():
			logging.info("STOPPING MIDI RECORDING ...")
			libsmf.stopRecording()
			exdirs = zynthian_gui_config.get_external_storage_dirs(self.ex_data_dir)
			if exdirs:
				filename = "{}/{}".format(exdirs[0], self.get_new_filename())
			else:
				filename = "{}/{}".format(self.capture_dir_sdc, self.get_new_filename())
			zynsmf.save(self.smf_recorder, filename)
			os.sync()

			self.update_list()
			return True

		else:
			return False


	def toggle_recording(self):
		logging.info("TOGGLING MIDI RECORDING ...")
		if not self.stop_recording():
			self.start_recording()


	def start_playing(self, fpath=None):
		self.stop_playing()

		if fpath is None:
			fpath = self.get_current_track_fpath()
		
		if fpath is None:
			logging.info("No track to play!")
			return

		try:
			zynsmf.load(self.smf_player, fpath)
			tempo = libsmf.getTempo(self.smf_player, 0)
			logging.info("STARTING MIDI PLAY '{}' => {}BPM".format(fpath, tempo))
			self.zyngui.zynseq.set_tempo(tempo)
			libsmf.startPlayback()
			self.zyngui.zynseq.transport_start("zynsmf")
#			self.zyngui.zynseq.libseq.transportLocate(0)
			self.current_playback_fpath=fpath
			if zynthian_gui_config.transport_clock_source == 0:
				self.show_playing_bpm()
			self.smf_timer = Timer(interval=1, function=self.check_playback)
			self.smf_timer.start()
		except Exception as e:
			logging.error("ERROR STARTING MIDI PLAY: %s" % e)
			self.zyngui.show_info("ERROR STARTING MIDI PLAY:\n %s" % e)
			self.zyngui.hide_info_timer(5000)

		#self.update_list()
		self.update_status_playback()
		return True


	def end_playing(self):
		logging.info("ENDING MIDI PLAY ...")
		self.zyngui.zynseq.transport_stop("zynsmf")
		if self.smf_timer:
			self.smf_timer.cancel()
			self.smf_timer = None
		self.current_playback_fpath = None
		self.hide_playing_bpm()
		#self.update_list()
		self.update_status_playback()


	def stop_playing(self):
		if libsmf.getPlayState() != zynsmf.PLAY_STATE_STOPPED:
			logging.info("STOPPING MIDI PLAY ...")
			libsmf.stopPlayback()
			sleep(0.1)
			self.end_playing()
			return True

		else:
			return False


	def toggle_playing(self, fpath=None):
		logging.info("TOGGLING MIDI PLAY ...")
		
		if fpath is None:
			fpath = self.get_current_track_fpath()

		if fpath and fpath != self.current_playback_fpath:
			self.start_playing(fpath)
		else:
			self.stop_playing()

	# Setup CUIA methods
	cuia_toggle_record = toggle_recording
	cuia_stop = stop_playing
	cuia_toggle_play = toggle_playing

	def show_playing_bpm(self):
		if self.bpm_zgui_ctrl:
			self.bpm_zgui_ctrl.config(self.zyngui.zynseq.zctrl_tempo)
			self.bpm_zgui_ctrl.show()
			self.bpm_zgui_ctrl.grid()
			self.loading_canvas.grid_remove()
		else:
			if zynthian_gui_config.layout['name'] == 'Z2':
				bmp_ctrl_index = 0
			else:
				bmp_ctrl_index = 2
			self.bpm_zgui_ctrl = zynthian_gui_controller(bmp_ctrl_index, self.main_frame, self.zyngui.zynseq.zctrl_tempo)
			self.loading_canvas.grid_remove()
			self.bpm_zgui_ctrl.grid(
				row=zynthian_gui_config.layout['ctrl_pos'][bmp_ctrl_index][0],
				column=zynthian_gui_config.layout['ctrl_pos'][bmp_ctrl_index][1],
				sticky='news'
			)
		self.zyngui.zynseq.update_tempo()


	def hide_playing_bpm(self):
		if self.bpm_zgui_ctrl:
			self.bpm_zgui_ctrl.hide()
			self.bpm_zgui_ctrl.grid_remove()
			self.loading_canvas.grid()


	# Implement engine's method
	def send_controller_value(self, zctrl):
		if zctrl.symbol=="bpm":
			self.zyngui.zynseq.set_tempo(zctrl.value)
			logging.debug("SET PLAYING BPM => {}".format(zctrl.value))


	def zynpot_cb(self, i ,dval):
		if not self.shown:
			return False
		
		if self.bpm_zgui_ctrl and self.bpm_zgui_ctrl.index == i:
			self.bpm_zgui_ctrl.zynpot_cb(dval)
			return True
		else:
			return super().zynpot_cb(i, dval)


	def plot_zctrls(self, force=False):
		super().plot_zctrls()
		if self.bpm_zgui_ctrl:
			if self.zyngui.zynseq.zctrl_tempo.is_dirty or force:
				self.bpm_zgui_ctrl.calculate_plot_values()
			self.bpm_zgui_ctrl.plot_value()


	def get_current_track_fpath(self):
		if not self.list_data:
			self.fill_list()
		#if selected track ...
		if self.list_data[self.index][1]>0:
			return self.list_data[self.index][0]
		#return first track in list if there is one ...
		fti = self.get_first_track_index()
		if fti is not None:
			return self.list_data[fti][0]
		#else return None
		else:
			return None


	def get_first_track_index(self):
		for i, row in enumerate(self.list_data):
			if row[1] > 0:
				return i
		return None


	def toggle_loop(self):
		if zynthian_gui_config.midi_play_loop:
			logging.info("MIDI play loop OFF")
			zynthian_gui_config.midi_play_loop=False
		else:
			logging.info("MIDI play loop ON")
			zynthian_gui_config.midi_play_loop=True
		zynconf.save_config({"ZYNTHIAN_MIDI_PLAY_LOOP": str(int(zynthian_gui_config.midi_play_loop))})
		self.update_status_loop(True)


	def update_wsleds(self, wsleds):
		wsl = self.zyngui.wsleds
		# REC button
		if self.zyngui.status_info['midi_recorder'] and "REC" in self.zyngui.status_info['midi_recorder']:
			wsl.wsleds.setPixelColor(wsleds[0], wsl.wscolor_red)
		else:
			wsl.wsleds.setPixelColor(wsleds[0], wsl.wscolor_alt)
		# STOP button
		wsl.wsleds.setPixelColor(wsleds[1], wsl.wscolor_alt)
		# PLAY button:
		if self.zyngui.status_info['midi_recorder'] and "PLAY" in self.zyngui.status_info['midi_recorder']:
			wsl.wsleds.setPixelColor(wsleds[2], wsl.wscolor_green)
		else:
			wsl.wsleds.setPixelColor(wsleds[2], wsl.wscolor_alt)


	def set_select_path(self):
		self.select_path.set("MIDI Recorder")

#------------------------------------------------------------------------------
