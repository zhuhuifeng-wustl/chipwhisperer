#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2013, Colin O'Flynn <coflynn@newae.com>
# All rights reserved.
#
# Find this and more at newae.com - this file is part of the chipwhisperer
# project, http://www.assembla.com/spaces/chipwhisperer
#
#    This file is part of chipwhisperer.
#
#    chipwhisperer is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    chipwhisperer is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with chipwhisperer.  If not, see <http://www.gnu.org/licenses/>.

__author__ = "Colin O'Flynn"

import sys
from PySide.QtCore import *
from PySide.QtGui import *
import os.path
sys.path.append('../common')
import pyqtgraph as pg
import pyqtgraph.multiprocess as mp
import tracereader_dpacontestv3
import tracereader_native
import re
import numpy as np
from scipy import signal

#For copying files when adding existing traces
import shutil
import glob

#For profiling support (not 100% needed)
import pstats, cProfile

#Reading trace config files
import ConfigParser

#General global settings/config
from cwanalyzer_common import CW_VERSION
from cwanalyzer_common import GlobalSettings

class traceItem():
    def __init__(self, configfile=None):
        self.enabled = False
        self.mappedRange = None
        self.numTraces = 0
        self.date = ""
        self.prefix = ""
        self.points = 0
        self.targetHW = ""
        self.targetSW = ""
        self.scope = ""
        self.samplerate = 0
        self.yscale = 1
        self.yunits = "digits"
        self.notes = ""

        self.trace = None

        self.configfile = None

    def loadTrace(self, configfile=None):

        if configfile:
            self.configfile = configfile

        config = ConfigParser.RawConfigParser()
        config.read(self.configfile)
        
        sname = "Trace Config"
        
        self.numTraces = config.getint(sname, 'NumTraces')
        self.date = config.get(sname, 'Date')
        self.prefix = config.get(sname, 'Prefix')
        self.points = config.getint(sname, 'Points')
        self.targetHW = config.get(sname, 'TargetHW')
        self.targetSW = config.get(sname, 'TargetSW')
        self.scope = config.get(sname, 'ScopeName')
        self.samplerate = config.get(sname, 'ScopeSampleRate')
        self.yscale = config.getfloat(sname, 'ScopeYScale')
        self.yunits = config.get(sname, 'ScopeYUnits')
        self.notes = config.get(sname, 'Notes')

    def saveTrace(self, configfile = None):
        if configfile:
            self.configfile = configfile

        config = ConfigParser.RawConfigParser()
        sname = "Trace Config"
        
        config.add_section(sname)
        config.set(sname, 'NumTraces', self.numTraces)
        config.set(sname, 'Date', self.date)
        config.set(sname, 'Prefix', self.prefix)
        config.set(sname, 'Points', self.points)
        config.set(sname, 'TargetHW', self.targetHW)
        config.set(sname, 'TargetSW', self.targetSW)
        config.set(sname, 'ScopeName', self.scope)
        config.set(sname, 'ScopeSampleRate', self.samplerate)
        config.set(sname, 'ScopeYScale', self.yscale)
        config.set(sname, 'ScopeYUnits', self.yunits)
        config.set(sname, 'Notes', self.notes)

        configfile = open(self.configfile, 'wb')
        config.write(configfile)
        configfile.flush()
        configfile.close()

    def checkTraceItem(self, itemname, localitem, changedlist):
        if localitem != self.__dict__[itemname]:                      
            changedlist.append(itemname)
            return True
        return False        

    def checkTrace(self, configfile = None):
        if configfile == None:
            configfile = self.configfile

        config = ConfigParser.RawConfigParser()
        config.read(configfile)
        
        sname = "Trace Config"

        numTraces = config.getint(sname, 'NumTraces')
        date = config.get(sname, 'Date')
        prefix = config.get(sname, 'Prefix')
        points = config.getint(sname, 'Points')
        targetHW = config.get(sname, 'TargetHW')
        targetSW = config.get(sname, 'TargetSW')
        scope = config.get(sname, 'ScopeName')
        samplerate = config.get(sname, 'ScopeSampleRate')
        yscale = config.getfloat(sname, 'ScopeYScale')
        yunits = config.get(sname, 'ScopeYUnits')
        notes = config.get(sname, 'Notes')

        #Compare memory to sections
        changed = False
        changedName = []
        changed = changed or self.checkTraceItem("numTraces", numTraces, changedName)
        changed = changed or self.checkTraceItem("date", date, changedName)
        changed = changed or self.checkTraceItem("prefix", prefix, changedName)
        changed = changed or self.checkTraceItem("points", points, changedName)
        changed = changed or self.checkTraceItem("targetHW", targetHW, changedName)
        changed = changed or self.checkTraceItem("targetSW", targetSW, changedName)
        changed = changed or self.checkTraceItem("scope", scope, changedName)
        changed = changed or self.checkTraceItem("samplerate", samplerate, changedName)
        changed = changed or self.checkTraceItem("yscale", yscale, changedName)
        changed = changed or self.checkTraceItem("yunits", yunits, changedName)
        changed = changed or self.checkTraceItem("notes", notes, changedName)

        #print changed
        #print changedName

        #TODO: Actually save or anything else
        
        return changed

class ManageTraces():
    def __init__(self, parent):
        self.dlg = parent
        self.NumTrace = 0
        self.NumPoint = 0
        self.knownkey = None

    def findMappedTrace(self, n):
        for t in self.dlg.traceList:
            if t.mappedRange:
                if n >= t.mappedRange[0] or n <= t.mappedRange[1]:
                    return t
        raise ValueError("n = %d not in mapped range"%n)

    def getTrace(self, n):
        t = self.findMappedTrace(n)
        return t.trace.getTrace(n - t.mappedRange[0])
    
    def getTextin(self, n):
        t = self.findMappedTrace(n)
        return t.trace.getTextin(n - t.mappedRange[0])

    def getTextout(self, n):
        t = self.findMappedTrace(n)
        return t.trace.getTextout(n - t.mappedRange[0])

    def getKnownKey(self):
        #For now all traces need to have same key
        return self.knownkey

    def UpdateTraces(self):
        #Find total (last mapped range)
        num = []
        pts = []

        for t in self.dlg.traceList:
            if t.mappedRange:
                num.append(t.mappedRange[1])
                pts.append(t.points)

                if self.knownkey == None:
                    self.knownkey = t.trace.knownkey

        try:
            self.NumTrace = max(num)
            self.NumPoint = max(pts)
        except:
            self.NumTrace = 0
            self.NumPoint = 0

from cwanalyzer_importdpav3 import ImportDPAv3

        
class ManageTracesDialog(QDialog):
    secName = "Trace Management"
    def __init__(self, parent=None):
        super(ManageTracesDialog, self).__init__(parent)
        self.parent = parent

        #This module is interface for others
        self.iface = ManageTraces(self)
        
        layout = QVBoxLayout()

        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(["Enabled", "Mapped Range", "Trace Num", "Points", "Date Captured", "File", "Target HW", "Target SW", "Scope", "Sample Rate", "Notes"])
       
        layout.addWidget(self.table)

        #temp = QPushButton("Add Blank")
        #temp.clicked.connect(self.addRow)
        #layout.addWidget(temp)

        importDPAv3 = QPushButton("Import DPAv3")
        importDPAv3.clicked.connect(self.importDPAv3)
        layout.addWidget(importDPAv3)

        copyExisting = QPushButton("Copy Existing and Add")
        copyExisting.clicked.connect(self.copyExisting)
        layout.addWidget(copyExisting)

        importExisting = QPushButton("Add Reference to Existing")
        importExisting.clicked.connect(self.importExisting)
        layout.addWidget(importExisting)

        # Set dialog layout
        self.setLayout(layout)

        self.setWindowTitle("Trace Management")

        self.newProject()

    def updatePreview(self):
        self.parent.updatePreview()

    def newProject(self):        
        self.traceList = []    
        return

    def checkProject(self, ask=True):
        #Check trace attributes
        for i in range(0, self.table.rowCount()):
            self.traceList[i].checkTrace()

        #Check out config

    def saveProject(self, config, configfilename):
        config.add_section(self.secName)
        for indx, t in enumerate(self.traceList):
            config.set(self.secName, 'tracefile%d'%indx, os.path.relpath(t.configfile, os.path.split(configfilename)[0]))
            config.set(self.secName, 'enabled%d'%indx, str(t.enabled))

    def loadProject(self, configfilename):
        config = ConfigParser.RawConfigParser()
        config.read(configfilename)
        alltraces = config.items(self.secName)

        self.newProject()

        fdir = os.path.split(configfilename)[0] + "/"

        for t in alltraces:
            if t[0].startswith("tracefile"):
                fname = fdir + t[1]
                print "Opening %s"%fname
                ti = traceItem()
                ti.loadTrace(fname)
                self.traceList.append(ti)
                self.addRow(ti)

            if t[0].startswith("enabled"):
                tnum = re.findall(r'[0-9]+', t[0])
                self.table.cellWidget(int(tnum[0]), self.findCol("Enabled")).setChecked(t[1] == "True")

    def findCol(self, name):
        """ Function is a hack/cheat to deal with movable headers if they become enabled """
        cols = self.table.columnCount()

        for i in range(0, cols):
            if self.table.horizontalHeaderItem(i).text() == name:
                return i

        raise ValueError("findCol argument not in table: %s"%name)

        
    def addRow(self, trace=None, location=None):
        if location == None:
            location = self.table.rowCount()
            
        self.table.insertRow(location)
        row = self.table.rowCount()-1
        cb = QCheckBox()
        cb.clicked.connect(self.validateTable)
        self.table.setCellWidget(row, self.findCol("Enabled"), cb)

        if trace:
            temp = QTableWidgetItem("%d"%trace.numTraces)
            temp.setFlags(temp.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.findCol("Trace Num"), temp)
            self.table.setItem(row, self.findCol("Date Captured"), QTableWidgetItem("%s"%trace.date))
            self.table.setItem(row, self.findCol("File"), QTableWidgetItem("%s"%trace.configfile))
            temp = QTableWidgetItem("%d"%trace.points)
            temp.setFlags(temp.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.findCol("Points"), temp)
            self.table.setItem(row, self.findCol("Target HW"), QTableWidgetItem("%s"%trace.targetHW))
            self.table.setItem(row, self.findCol("Target SW"), QTableWidgetItem("%s"%trace.targetSW))
            self.table.setItem(row, self.findCol("Scope"), QTableWidgetItem("%s"%trace.scope))
            self.table.setItem(row, self.findCol("Sample Rate"), QTableWidgetItem("%s"%trace.samplerate))
            self.table.setItem(row, self.findCol("Notes"), QTableWidgetItem("%s"%trace.notes))

        self.validateTable()

    def validateTable(self):
        startTrace = 0
        for i in range(0, self.table.rowCount()):
            if self.table.cellWidget(i, self.findCol("Enabled")).isChecked():
                self.traceList[i].enabled = True
                tlen = self.traceList[i].numTraces
                self.traceList[i].mappedRange = [startTrace, startTrace+tlen]
                self.table.setItem(i, self.findCol("Mapped Range"), QTableWidgetItem("%d-%d"%(startTrace, startTrace+tlen)))
                startTrace = startTrace + tlen + 1

                if self.traceList[i].trace == None:
                    self.traceList[i].trace = tracereader_native.tracereader_native()
                    path = os.path.split(self.traceList[i].configfile)[0]
                    self.traceList[i].trace.loadAllTraces(path, self.traceList[i].prefix)
                
            else:
                self.traceList[i].enabled = False
                self.traceList[i].mappedRange = None
                self.table.setItem(i, self.findCol("Mapped Range"), QTableWidgetItem(""))

        self.iface.UpdateTraces()
        self.updatePreview()
        
    def importDPAv3(self):
        imp = ImportDPAv3(self)
        imp.exec_()
        self.importExisting(imp.getTraceCfgFile())
        self.updatePreview()

    def importExisting(self, fname=None):
        if fname == None:
            fname, _ = QFileDialog.getOpenFileName(self, 'Open file',GlobalSettings.value("trace_last_file"),'*.cfg')
            if fname:
                GlobalSettings.setValue("trace_last_file", fname)

        if fname:
            #Add to file list
            ti = traceItem()
            ti.loadTrace(fname)
            self.traceList.append(ti)
            self.addRow(ti)
            self.updatePreview()

    def copyExisting(self, fname=None):
        if fname == None:
            fname, _ = QFileDialog.getOpenFileName(self, 'Open file',GlobalSettings.value("trace_last_file"),'*.cfg')
            if fname:
                GlobalSettings.setValue("trace_last_file", fname)

        if fname:
            #Get our project directory
            targetdir = self.parent.cwp.traceslocation + "/"
            cfgname = os.path.split(fname)[1]
            srcdir = os.path.split(fname)[0] + "/"            
            newcfgname = targetdir + cfgname

            #Get prefix from config file
            config = ConfigParser.RawConfigParser()
            config.read(fname)
            prefix = config.get("Trace Config", "prefix")
            newprefix = prefix

            #Check if we'll be overwriting things
            newprefix = prefix
            while(os.path.exists(newcfgname)):
                npstripped = newprefix.rstrip("_")
                newprefix = QInputDialog.getText(self, "Enter New Prefix", "Project already contains trace with\nprefix %s. Please enter new prefix:"%npstripped, text=npstripped)
                if newprefix[1] == True:
                    newcfgname = targetdir + cfgname.replace(prefix.rstrip("_"), newprefix[0])
                    newprefix = newprefix[0] + "_"
                else:
                    return
                
            #Change prefix in config file & write new one
            config.set("Trace Config", "prefix", newprefix)
            configfile = open(newcfgname, 'wb')
            config.write(configfile)        
            configfile.close()
            
            #Copy anything with same prefix, changing as 
            for filename in glob.glob(os.path.join(srcdir, '%s*'%prefix)):
                if os.path.isfile(filename):
                    targetfile = os.path.split(filename)[1].replace(prefix, newprefix)
                    shutil.copy(filename, targetdir + targetfile)
            
            #Add new trace to file list
            ti = traceItem()
            ti.loadTrace(newcfgname)
            self.traceList.append(ti)
            self.addRow(ti)

            self.updatePreview()
