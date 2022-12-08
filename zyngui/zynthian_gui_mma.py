#!/usr/bin/python3
# -*- coding: utf-8 -*-
#******************************************************************************
# ZYNTHIAN PROJECT: Zynthian GUI
#
# Zynthian GUI Step-Sequencer Pad Trigger Class
#
# Copyright (C) 2015-2022 Fernando Moyano <jofemodo@zynthian.org>
#                         Brian Walton <brian@riban.co.uk>
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

import tkinter
import logging
import tkinter.font as tkFont
from math import sqrt
from PIL import Image, ImageTk
from time import sleep
from threading import Timer
from collections import OrderedDict
import subprocess
import tempfile
from contextlib import suppress
import os

# Zynthian specific modules
from zyngui import zynthian_gui_config
from zyngui.zynthian_gui_patterneditor import EDIT_MODE_NONE
from . import zynthian_gui_base
from zyncoder.zyncore import lib_zyncore
from zynlibs.zynseq import zynseq
from zynlibs.zynsmf import zynsmf # Python wrapper for zynsmf (ensures initialised and wraps load() function)
from zynlibs.zynsmf.zynsmf import libsmf # Direct access to shared library 
import tempfile
import jack

#------------------------------------------------------------------------------
# Zynthian Step-Sequencer Sequence / Pad Trigger GUI Class
#------------------------------------------------------------------------------
SELECT_BORDER	= zynthian_gui_config.color_on

CHORD_NAMES   = [ "Db", "Eb", "Gb", "Ab", "Bb", "C", "D", "E", "F", "G", "A", "B"]
CHORD_FLAV    = [ "M7", "m7", "7", "m", ""]
#GROOVES       = [ "blues128", "rhumba", "50srock", "60srock", "popballad1", "popbalad1plus" ] 
MY_DATA_DIR   = "/zynthian/zynthian-my-data" # TODO : clarify

class chord:
    def __init__(self, chord):
        for base in CHORD_NAMES:
            if chord.startswith(base):
                self.base = CHORD_NAMES.index(base)
                break
        self.flavor = CHORD_FLAV.index("")
        for flavor in CHORD_FLAV:
            if chord.endswith(flavor):
                 self.flavor = CHORD_FLAV.index(flavor)
                 break

    def getChord(self):
        return "{}{}".format(CHORD_NAMES[self.base], CHORD_FLAV[self.flavor])

    def setBase(self,base):
        self.base = CHORD_NAMES.index(base)

    def setFlavor(self, flavor):
        self.flavor = CHORD_FLAV.index(flavor)

    def changeBase(self, offset):
        self.base += offset
        self.base %= len(CHORD_NAMES)
    
    def changeFlavor(self, offset):
        self.flavor += offset
        self.flavor %= len(CHORD_FLAV)

class groovelist:
	def __init__(self):
		self.grooves = list()
		self.file = os.path.join(MY_DATA_DIR, "mma/grooves.lst")
		print(self.file)
		with open(self.file) as f:
			for g in f.readlines():
				if not g.startswith("#"):
					self.grooves.append(g)

	def __getitem__(self, index):
		return self.grooves[index]

	def __len__(self):
		return len(self.grooves)

# Class implements mma
class zynthian_gui_mma(zynthian_gui_base.zynthian_gui_base):

    # Function to initialise class
	def __init__(self):
		logging.getLogger('PIL').setLevel(logging.WARNING)

		self.columns = 4 # Quantity of columns in grid
		self.selected_pad = 0
		self.edit_pad = False
		self.playing = False
		self.played_bar = 0
		self.current_jack_bar = 0
		self.start_jack_bar = 0
		self.groove = 0
		self.grooves = groovelist()
		
		self.smf_player = None # Pointer to SMF player
		super().__init__()
		try:
			self.smf_player = libsmf.addSmf()
			libsmf.attachPlayer(self.smf_player)
		except Exception as e:
			logging.error(e)

		self.jack_client = jack.Client('zynmma')


		# Geometry vars
		self.column_width = self.width / self.columns
		self.row_height = self.height / self.columns
		self.select_thickness = 1 + int(self.width / 400) # Scale thickness of select border based on screen

		# Pad grid
		self.grid_canvas = tkinter.Canvas(self.main_frame,
			width=self.width,
			height=self.height,
			bd=0,
			highlightthickness=0,
			bg = zynthian_gui_config.color_bg)
		self.main_frame.columnconfigure(0, weight=1)
		self.main_frame.rowconfigure(0, weight=1)
		self.grid_canvas.grid()

		# Selection highlight
		self.selection = self.grid_canvas.create_rectangle(0, 0, self.column_width, self.row_height, fill="", outline=SELECT_BORDER, width=self.select_thickness, tags="selection")

		#self.chord_grid =  list()
		self.chord_grid = [ chord("Am"), chord("F"), chord("C"), chord("G7") ]

	# Function to show GUI
	#   params: Misc parameters
	def build_view(self):
		self.set_title("MMA")

	# Function to hide GUI
	def hide(self):
		super().hide()

	def update_layout(self):
		super().update_layout()
		self.redraw_pending = 2
		self.update_grid()

	def refresh_played_bar(self):
		current_jack_bar = 0
		state, pos = self.jack_client.transport_query()
		with suppress(KeyError):
			current_jack_bar = pos['bar']
		if current_jack_bar != self.current_jack_bar:
			self.current_jack_bar = current_jack_bar
			if self.played_bar >= 0:
				cell = self.grid_canvas.find_withtag("pad:%d"%(self.played_bar))
				self.grid_canvas.itemconfig(cell, fill="grey")
			self.played_bar = current_jack_bar - self.start_jack_bar
			self.played_bar %= len(self.chord_grid)
			cell = self.grid_canvas.find_withtag("pad:%d"%(self.played_bar))
			self.grid_canvas.itemconfig(cell, fill="green")


	def refresh_status(self, status):
		super().refresh_status(status)
		self.update_grid()
		if self.playing:
			self.refresh_played_bar()

	# Function to clear and calculate grid sizes
	def update_grid(self):
		if self.redraw_pending:
			self.redraw_pending = 0
			for index in range(16):
				chord_y = int(index / self.columns) * self.row_height
				chord_x = index % self.columns * self.column_width
				self.grid_canvas.create_rectangle(chord_x, chord_y, chord_x + self.column_width - 2, chord_y + self.row_height - 2, fill='grey', width=0, tags=("pad:%d"%(index)))

				self.grid_canvas.create_text(int(chord_x + self.column_width / 2), int(chord_y + 0.01 * self.row_height),
				    width=self.column_width,
				    anchor="n", justify="center",
				    font=tkFont.Font(family=zynthian_gui_config.font_topbar[0],
					size=int(self.row_height * 0.2)),
				    fill=zynthian_gui_config.color_panel_tx,
				    tags=("lbl_pad:%d"%(index),"trigger_%d"%(index)))
				if (index < len(self.chord_grid)):
				    self.grid_canvas.itemconfig("lbl_pad:%d"%(index), text=self.chord_grid[index].getChord())
				self.update_selection_cursor()

	# Function to move selection cursor
	def update_selection_cursor(self):
		row = int(self.selected_pad / self.columns)
		col = self.selected_pad % self.columns
		self.grid_canvas.coords(self.selection,
			1 + col * self.column_width, 1 + row * self.row_height,
			(1 + col) * self.column_width - self.select_thickness, (1 + row) * self.row_height - self.select_thickness)
		self.grid_canvas.tag_raise(self.selection)
	
	# Function to handle zynpots value change
	#   encoder: Zynpot index [0..n]
	#   dval: Zynpot value change
	def zynpot_cb(self, encoder, dval):
		if super().zynpot_cb(encoder, dval):
			return
		if encoder == zynthian_gui_config.ENC_BACK:
			if (self.edit_pad):
				if (self.selected_pad < len(self.chord_grid)):
					self.chord_grid[self.selected_pad].changeBase(dval)
					self.grid_canvas.itemconfig("lbl_pad:%d"%(self.selected_pad), text=self.chord_grid[self.selected_pad].getChord())
			else:
				# BACK encoder adjusts horizontal pad selection
				pad = self.selected_pad + self.columns * dval
				col = int(pad / self.columns)
				row = pad % self.columns
				if col >= self.columns:
					col = 0
					row += 1
					pad = row + self.columns * col
				elif pad < 0:
					col = self.columns -1
					row -= 1
					pad = row + self.columns * col
				if row < 0 or row >= self.columns or col >= self.columns:
					return
				self.selected_pad = pad
				self.update_selection_cursor()
		elif encoder == zynthian_gui_config.ENC_SELECT:
			if self.edit_pad:
				if (self.selected_pad < len(self.chord_grid)):
					self.chord_grid[self.selected_pad].changeFlavor(dval)
					self.grid_canvas.itemconfig("lbl_pad:%d"%(self.selected_pad), text=self.chord_grid[self.selected_pad].getChord())
			else:
				# SELECT encoder adjusts vertical pad selection
				pad = self.selected_pad + dval
				self.selected_pad = pad
				self.update_selection_cursor()
		elif encoder == zynthian_gui_config.ENC_SNAPSHOT:
				self.zyngui.zynseq.nudge_tempo(dval)
				self.set_title("Tempo: {:.1f}".format(self.zyngui.zynseq.get_tempo()), None, None, 2)
		elif encoder == zynthian_gui_config.ENC_LAYER:
				self.groove += dval
				self.groove %= len(self.grooves)
				self.set_title("Groove: {}".format(self.grooves[self.groove]), None, None, 2)
				pass

	def toggle_pad(self):
		# check if need to allocate new bar
		if self.selected_pad > len(self.chord_grid):
			# too far away, abort
			return True

		if self.selected_pad == len(self.chord_grid):
			new = "C"
			try:
				new = self.chord_grid[self.selected_pad - 1].getChord()
			except:
				pass
			# allocate new chord, with data from previous bar
			self.chord_grid.append(chord(new))
			self.grid_canvas.itemconfig("lbl_pad:%d"%(self.selected_pad), text=self.chord_grid[self.selected_pad].getChord())
                

		self.edit_pad = not self.edit_pad
		cell = self.grid_canvas.find_withtag("pad:%d"%(self.selected_pad))
		if self.edit_pad:
			self.grid_canvas.itemconfig(cell, fill="blue")
		else:
			self.grid_canvas.itemconfig(cell, fill="grey")

	def remove_bar(self):
		# can only remove last bar
		if self.selected_pad == len(self.chord_grid) - 1:
			self.chord_grid.pop()
			self.grid_canvas.itemconfig("lbl_pad:%d"%(self.selected_pad), text="")
		return True

	# Function to handle SELECT button press
	#	type: Button press duration ["S"=Short, "B"=Bold, "L"=Long]
	def switch_select(self, type='S'):
		if super().switch_select(type):
			return True
		if type == 'S':
			return self.toggle_pad()
		if type == "B":
			return self.remove_bar()


	# Function to handle switch press
	#	switch: Switch index [0=Layer, 1=Back, 2=Snapshot, 3=Select]
	#	type: Press type ["S"=Short, "B"=Bold, "L"=Long]
	#	returns True if action fully handled or False if parent action should be triggered
	def switch(self, switch, type):
		self.zyngui.zynseq.disable_midi_learn()
		if switch == zynthian_gui_config.ENC_SNAPSHOT and type == 'B':
			if not self.playing:
				self.start_playing()
			else:
				self.stop_playing()
			return True
		elif switch == zynthian_gui_config.ENC_LAYER and type == 'B':
			self.show_menu()
			return True
		return False


	#	CUIA Actions
	# Function to handle CUIA ARROW_RIGHT
	def arrow_right(self):
		self.zynpot_cb(zynthian_gui_config.ENC_SELECT, 1)


	# Function to handle CUIA ARROW_LEFT
	def arrow_left(self):
		self.zynpot_cb(zynthian_gui_config.ENC_SELECT, -1)


	# Function to handle CUIA ARROW_UP
	def arrow_up(self):
		if self.param_editor_zctrl:
			self.zynpot_cb(zynthian_gui_config.ENC_SELECT, 1)
		else:
			self.zynpot_cb(zynthian_gui_config.ENC_BACK, -1)


	# Function to handle CUIA ARROW_DOWN
	def arrow_down(self):
		if self.param_editor_zctrl:
			self.zynpot_cb(zynthian_gui_config.ENC_SELECT, -1)
		else:
			self.zynpot_cb(zynthian_gui_config.ENC_BACK, 1)

	def stop_playing(self):
		if libsmf.getPlayState()!=zynsmf.PLAY_STATE_STOPPED:
			logging.info("STOPPING MIDI PLAY ...")
			libsmf.stopPlayback()
			self.playing=False
			cell = self.grid_canvas.find_withtag("pad:%d"%(self.played_bar))
			self.grid_canvas.itemconfig(cell, fill="grey")
			os.remove(self.current_midi)
			sleep(0.1)

	def start_playing(self, fpath=None):
		self.stop_playing()
		infile = tempfile.NamedTemporaryFile()
		tempo = self.zyngui.zynseq.get_tempo()
		infile.write("Tempo {}\n".format(tempo).encode())
		infile.write("Groove {}\n".format(self.grooves[self.groove]).encode())
		infile.write("Time 4\n".encode())
		infile.write("Repeat\n".encode())
		barnum = 1
		for bar in self.chord_grid:
		    barstring = "{} {}\n".format(barnum, bar.getChord())
		    barnum += 1
		    infile.write(barstring.encode())
		infile.write("RepeatEnd 10\n".encode())

		infile.flush()
		fpath = "{}.mid".format(infile.name)
		command = ["mma", "-1", "-f", fpath, infile.name]
		process = subprocess.run(command)

		infile.close()
		self.current_midi = fpath

		try:
			zynsmf.load(self.smf_player,fpath)
			#tempo = libsmf.getTempo(self.smf_player, 0)
			logging.info("STARTING MIDI PLAY '{}' => {}BPM".format(fpath, tempo))
			#self.zyngui.zynseq.set_tempo(tempo)
			libsmf.startPlayback()
			libsmf.setLoop(True)
			self.zyngui.zynseq.transport_start("zynsmf")
			self.zyngui.zynseq.libseq.transportLocate(0)
			self.zyngui.zynseq.libseq.setTransportToStartOfBar()
			self.current_playback_fpath=fpath
			state, pos = self.jack_client.transport_query()
			with suppress(KeyError):
				current_jack_bar = pos['bar']
				self.start_jack_bar = current_jack_bar
			self.playing = True
			self.played_bar = 0
			self.refresh_played_bar()
		except Exception as e:
			logging.error("ERROR STARTING MIDI PLAY: %s" % e)
			self.zyngui.show_info("ERROR STARTING MIDI PLAY:\n %s" % e)
			self.zyngui.hide_info_timer(5000)


#------------------------------------------------------------------------------
