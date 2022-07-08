################################################################################
# Copyright 2016-2020 Advanced Micro Devices, Inc. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell cop-
# ies of the Software, and to permit persons to whom the Software is furnished
# to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IM-
# PLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNE-
# CTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
################################################################################

from __future__ import print_function
from .Common import globalParameters, printExit
from copy import deepcopy
import ctypes
# Global to print module names around strings
printModuleNames = 0

def printItemList(listOfItems, tag="__unnamed__"):
  header = "="*40
  print("%s\nbegin list %s\n%s"%(header, tag, header))
  for i, item in enumerate(listOfItems):
    item = list(item) if isinstance(item, tuple) else [item]
    print("list[%s] %s"%(i, "-"*30))
    for j, t in enumerate(item):
      ostream = t.prettyPrint()
      ostream = ostream[:-1] if len(ostream)>0 and ostream[-1:] == '\n' else ostream
      print(ostream)
  print("%s\nend list %s\n%s"%(header, tag, header))

class Item:
  """
  Base class for Modules, Instructions, etc
  Item is a atomic collection of or more instructions and commentsA
  """
  def __init__(self):
    self.parent = ""

  def toStr(self):
    return str(self)

  def countType(self,ttype):
    return int(isinstance(self, ttype))

  def prettyPrint(self, indent=""):
    ostream = ""
    ostream += "%s%s "%(indent, type(self).__name__)
    ostream += str(self)
    return ostream

class Module(Item):
  """
  Modules contain lists of text instructions, Inst objects, or additional modules
  They can be easily converted to string that represents all items in the list
  and can be mixed with standard text.
  The intent is to allow the kernel writer to express the structure of the
  code (ie which instructions are a related module) so the scheduler can later
  make intelligent and legal transformations.
  """
  def __init__(self, name=""):
    self.name     = name
    self.itemList = []
    self.tempVgpr = None

  def findNamedItem(self, targetName):
    return next((item for item in self.itemList if item.name==targetName), None)

  def setInlineAsmPrintMode(self, mode):
    for item in self.itemList:
      if isinstance(item, Inst):
        item.setInlineAsmPrintMode(mode)
      elif isinstance(item, Module):
        item.setInlineAsmPrintMode(mode)

  def __str__(self):
    s = ""
    if printModuleNames:
      s += "// %s { \n" % self.name
    s += "".join([str(x) for x in self.itemList])
    if printModuleNames:
      s += "// } %s\n" % self.name
    return s

  def addCode(self, item):
    """
    Add specified item to the list of items in the module.
    Item MUST be a Item (not a string) - can use
    addText(...)) to add a string.
    All additions to itemList should use this function.

    Returns item to facilitate one-line create/add patterns
    """
    #assert (isinstance(item, Item)) # for debug
    if isinstance(item,Item):
      item.parent = self
      self.itemList.append(item)
    elif isinstance(item,str):
      self.addCode(TextBlock(item))
    else:
      assert 0, "unknown item type (%s) for Module.addCode. item=%s"%(type(item), item)
    return item

  def addCodeBeforeItem(self, item, newItem):
    """
    Add specified item to the list of items in the module.
    Item MUST be a Item (not a string) - can use
    addText(...)) to add a string.
    All additions to itemList should use this function.

    Returns item to facilitate one-line create/add patterns
    """
    #assert (isinstance(item, Item)) # for debug
    if isinstance(newItem,Item):
      item.parent = self
      itemIdx = -1
      for idx, selfItem in enumerate(self.itemList):
        if item == selfItem:
          itemIdx = idx
          break
      if itemIdx != -1:
        self.itemList.insert(idx, newItem)
    elif isinstance(newItem,str):
      self.addCodeBeforeItem(item, TextBlock(newItem))
    else:
      assert 0, "unknown item type (%s) for Module.addCodeByIndex. item=%s"%(type(item), item)
    return item

  def findIndex(self, targetItem):
    if isinstance(targetItem, Item):
      return self.itemList.index(targetItem)
    return -1

  def addComment0(self, comment):
    """
    Convenience function to format arg as a comment and add TextBlock item
    This comment is a single line /* MYCOMMENT  */
    """
    self.addCode(TextBlock("/* %s */\n"%comment))

  def addComment1(self, comment):
    """
    Convenience function to format arg as a comment and add TextBlock item
    This comment is a blank line followed by /* MYCOMMENT  */
    """
    self.addCode(TextBlock("\n/* %s */\n"%comment))

  def addInst(self, *args):
    """
    Convenience function to construct a single Inst and add to items
    """
    self.addCode(Inst(*args))

  def addText(self,text):
    """
    Convenience function to construct a TextBlock and add to items
    """
    self.addCode(TextBlock(text))

  def prettyPrint(self,indent=""):
    ostream = ""
    ostream += '%s%s "%s"\n'%(indent, type(self).__name__, self.name)
    for i in self.itemList:
      ostream += i.prettyPrint(indent.replace("|--", "| ") + "|--")
    return ostream
    """
    Test code:
      mod1 = Code.Module("TopModule")
      mod2 = Code.Module("Module-lvl2")
      mod2.addCode(Code.Inst("bogusInst", "comments"))
      mod3 = Code.Module("Module-lvl3")
      mod3.addCode(Code.TextBlock("bogusTextBlock\nbogusTextBlock2\nbogusTextBlock3"))
      mod3.addCode(Code.GlobalReadInst("bogusGlobalReadInst", "comments"))
      mod2.addCode(mod3)
      mod1.addCode(mod2)
      mod1.addCode(Code.Inst("bogusInst", "comments"))
      mod1.addCode(mod2)

      print(mod1.prettyPrint())
    Output:
      Module "TopModule"
      |--Module "Module-lvl2"
      | |--Inst bogusInst                                          // comments
      | |--Module "Module-lvl3"
      | | |--TextBlock
      | | | |--bogusTextBlock
      | | | |--bogusTextBlock2
      | | | |--bogusTextBlock3
      | | |--GlobalReadInst bogusGlobalReadInst                                // comments
      |--Inst bogusInst                                          // comments
      |--Module "Module-lvl2"
      | |--Inst bogusInst                                          // comments
      | |--Module "Module-lvl3"
      | | |--TextBlock
      | | | |--bogusTextBlock
      | | | |--bogusTextBlock2
      | | | |--bogusTextBlock3
      | | |--GlobalReadInst bogusGlobalReadInst                                // comments
    """

  def countTypeList(self, ttypeList):
    count = 0
    # add "Module" type to type list filter, where we want to count recursively
    # the types under "Module"
    if Module not in ttypeList:
      ttypeList.append(Module)
    for ttype in ttypeList:
      count += self.countType(ttype)
    return count

  def countType(self,ttype):
    """
    Count number of items with specified type in this Module
    Will recursively count occurrences in submodules
    (Overrides Item.countType)
    """
    count=0
    for i in self.itemList:
      if isinstance(i, Module):
        count += i.countType(ttype)
      else:
        count += int(isinstance(i, ttype))
    return count

  def count(self):
    count=0
    for i in self.itemList:
      if isinstance(i, Module):
        count += i.count()
      else:
        count += 1
    return count

  def items(self):
    """
    Return list of items in the Module
    Items may be other Modules, TexBlock, or Inst
    """
    return self.itemList

  def removeItemByIndex(self, index):
    """
    Remove item from itemList, remove the last element if
    exceed length of the itemList
    Items may be other Modules, TexBlock, or Inst
    """
    if index >= len(self.itemList):
      index = -1
    del self.itemList[index]

  def removeItemsByName(self, name):
    """
    Remove items from itemList
    Items may be other Modules, TexBlock, or Inst
    """
    self.itemList = [ x for x in self.itemList if x.name != name ]

  def flatitems(self):
    """
    Return flattened list of items in the Module
    Items in sub-modules will be flattened into single list
    Items may be TexBlock or Inst
    """
    flatitems = []
    for i in self.itemList:
      if isinstance(i, Module):
        flatitems += i.flatitems()
      else:
        flatitems.append(i)
    return flatitems

  def addTempVgpr(self, vgpr):
    self.tempVgpr = vgpr

class StructuredModule(Module):
  def __init__(self, name=None):
    Module.__init__(self,name)
    self.header = Module("header")
    self.middle = Module("middle")
    self.footer =  Module("footer")

    self.addCode(self.header)
    self.addCode(self.middle)
    self.addCode(self.footer)


class Label (Item):
  """
  Label that can be the target of a jump.
  """
  def __init__(self, labelNum, comment):
    self.labelNum = labelNum
    self.comment = comment

  def __str__(self):
    t = "label_%04u:" % (self.labelNum)
    if self.comment:
      t += "  /// %s" % self.comment
    t += "\n"
    return t


class TextBlock(Item):
  """
  An unstructured block of text that can contain comments and instructions
  """
  def __init__(self,text):
    assert(isinstance(text, str))
    self.text = text
    self.name = text

  def __str__(self):
    return self.text

  def prettyPrint(self, indent=""):
    ostream = ""
    ostream += "%s%s "%(indent, type(self).__name__)
    l = [_i for _i in str(self).split("\n") if len(_i)>0]
    l.insert(0, "")
    ostream += "%s"%(("\n"+indent.replace("|-", "| |-")).join(l))
    ostream += "\n"
    return ostream

class Inst(Item):
  """
  Inst is a single instruction and is base class for other instructions.
  Currently just stores text+comment but over time may grow
  """
  def __init__(self, *args):
    params = args[0:len(args)-1]
    self.comment = args[len(args)-1]
    assert(isinstance(self.comment, str))
    self.inst   = params[0]
    self.name   = self.inst
    self.params = ""
    if len(params) > 1:
      self.params = list(params[1:])
    self.outputInlineAsm = False

  def setInlineAsmPrintMode(self, mode):
    isinstance(mode, bool)
    self.outputInlineAsm = mode

  def formatWithComment(self, formatting, comment, *args):
    instStr     = formatting %(args)
    return "%-50s // %s\n" % (instStr, comment)

  def copy(self, inst):
    assert(isinstance(inst, Inst))
    self.name    = deepcopy(inst.name)
    self.inst    = deepcopy(inst.inst)
    self.comment = deepcopy(inst.comment)
    self.params  = deepcopy(inst.params)
    self.outputInlineAsm = inst.outputInlineAsm

  def __str__(self):
    params = [self.inst]
    params.extend(self.params)
    formatting = "\"%s" if self.outputInlineAsm else "%s"
    if len(params) > 1:
      formatting += " %s"
    for i in range(0, len(params)-2):
      formatting += ", %s"
    if self.outputInlineAsm:
      formatting += "\\n\\t\""
    return self.formatWithComment(formatting, self.comment, *params)

class WaitCnt (Module):
  """
  Construct a waitcnt from specified lgkmcnt and vmcnt:
  lgkmcnt, vmcnt:
    if -1 then will not be added to the wait term.

  If lgkmcnt=vmcnt= -1 then the waitcnt is a nop and
  an instruction with a comment is returned.
  """
  def __init__(self, version,lgkmcnt=-1,vmcnt=-1,comment=""):
    super().__init__("wait")

    self.version = version
    self.lgkmcnt = lgkmcnt
    self.vmcnt   = vmcnt
    self.comment = "lgkmcnt={} vmcnt={}".format(lgkmcnt, vmcnt) + comment

    # let this derived class play nicely with Module.prettyPrint()
    self.__dict__.update(self.instructions().__dict__)

  def instructions(self):
    rv = Module()
    main_args = []
    wait_store = False
    if self.lgkmcnt != -1:
      currentIsa = globalParameters["CurrentISA"]
      maxLgkmcnt = globalParameters["AsmCaps"][currentIsa]["MaxLgkmcnt"]
      main_args += ["lgkmcnt(%u)" % (min(self.lgkmcnt,maxLgkmcnt))]
      wait_store = True

    if self.vmcnt != -1:
      main_args += ["vmcnt(%u)" % self.vmcnt]

    if len(main_args) > 0:
      rv.addInst("s_waitcnt", *main_args, self.comment)
      if wait_store and self.version[0] == 10 and self.vmcnt != -1:
        rv.addInst("s_waitcnt_vscnt", "null", self.vmcnt, "writes")
    else:
      rv.addComment0(self.comment)

    return rv

  def __str__(self):
    return str(self.instructions())

# uniq type that can be used in Module.countType
class GlobalReadInst (Inst):
  def __init__(self,*args):
    Inst.__init__(self,*args)

# uniq type that can be used in Module.countType
class LocalWriteInst (Inst):
  def __init__(self,issuelatency,*args):
    self.IssueLatency = issuelatency
    Inst.__init__(self,*args)

# uniq type that can be used in Module.countType
class LocalReadInst (Inst):
  def __init__(self,issuelatency,readToTempVgpr,*args):
    self.IssueLatency = issuelatency
    self.readToTempVgpr = readToTempVgpr
    Inst.__init__(self,*args)

################################################################################
# MFMA Instruction
################################################################################
class  MFMAInst (Inst):

  """
  Construct a MFMA instruction from specified precision Type, aIndex, bIndex, PLR, innerUnroll:

  dataType:
  aIndex:  index value from range (0, kernel["ThreadTile0"])
  bIndex:  index value from range (0, kernel["ThreadTile1"])

  PLR:     valida values 0,1

  usage Module.addCode(Code.MFMAInst())

  """
  def  __init__(self,kernel,aIdx,bIdx,PLRval,innerUnroll):
       self.endLine = ""
       self.version = globalParameters["CurrentISA"]
       self.kernel  = kernel
       self.aIdx    = aIdx
       self.bIdx    = bIdx
       self.PLR     = PLRval
       self.innerUnroll = innerUnroll

  def __str__(self):
      # single precision
      kStr = ""
      numOfRowsperMfma = 1
      numOfRowInsts = self.kernel["ThreadTile0"]/numOfRowsperMfma
      #numOfColInsts = kernel["ThreadTile1"]/kernel["MatrixInstN"]
      numOfDstRgs = (self.kernel["MatrixInstN"] * self.kernel["MatrixInstM"] * self.kernel["MatrixInstB"] // self.kernel["WavefrontSize"])
      if self.kernel["ProblemType"]["DataType"].isSingle():
        for iui in range(0, self.innerUnroll):
           cStr = "a[(%u+%u*%u)*%u):((((%u+%u*%u)*%u)+%u)-1)]" % (self.aIdx,self.bIdx,numOfRowInsts,numOfDstRgs,self.aIdx,numOfDstRgs,self.bIdx,numOfRowInsts,numOfDstRgs)
           aStr = "v[%s+%u]" \
               % ("vgprValuA_X%u_I%u"%(self.PLR,iui), self.aIdx)
           bStr = "v[%s+%u]" \
               % ("vgprValuB_X%u_I%u"%(self.PLR,iui), self.bIdx)
           kStr += "v_mfma_f32_%ux%ux%uf32 %s, %s, %s, %s%s" % (self.kernel["MatrixInstM"], self.kernel["MatrixInstN"], self.kernel["MatrixInstK"], cStr, aStr, bStr, cStr, self.endLine)
      else:
        printExit("Assembly doesn't support %s" % self.kernel["ProblemType"]["DataType"])

      return self.formatWithComment(kStr, "")

  def getLatency(self):
      # return latency in cycles
      return  (self.kernel["MatrixInstM"] // 4 ) * 8
class BitfieldStructure(ctypes.Structure):
  def field_desc(self, field):
    fname = field[0]
    bits = " ({}b)".format(field[2]) if len(field) > 2 else ""
    value = getattr(self, fname)
    return "{0}{1}: {2}".format(fname, bits, value)

  def desc(self):
    return '\n'.join([self.field_desc(field) for field in self._fields_])

class BitfieldUnion(ctypes.Union):
  def __str__(self):
    return "0x{0:08x}".format(self.value)

  def desc(self):
    return "hex: {}\n".format(self) + self.fields.desc()

class SrdUpperFields9XX(BitfieldStructure):
  _fields_ = [("dst_sel_x",      ctypes.c_uint, 3),
              ("dst_sel_y",      ctypes.c_uint, 3),
              ("dst_sel_z",      ctypes.c_uint, 3),
              ("dst_sel_w",      ctypes.c_uint, 3),
              ("num_format",     ctypes.c_uint, 3),
              ("data_format",    ctypes.c_uint, 4),
              ("user_vm_enable", ctypes.c_uint, 1),
              ("user_vm_mode",   ctypes.c_uint, 1),
              ("index_stride",   ctypes.c_uint, 2),
              ("add_tid_enable", ctypes.c_uint, 1),
              ("_unusedA",       ctypes.c_uint, 3),
              ("nv",             ctypes.c_uint, 1),
              ("_unusedB",       ctypes.c_uint, 2),
              ("type",           ctypes.c_uint, 2)]

  @classmethod
  def default(cls):
    return cls(data_format = 4)

class SrdUpperValue9XX(BitfieldUnion):
  _fields_ = [("fields", SrdUpperFields9XX), ("value", ctypes.c_uint32)]

  @classmethod
  def default(cls):
    return cls(fields=SrdUpperFields9XX.default())

class SrdUpperFields10XX(BitfieldStructure):
  _fields_ = [("dst_sel_x",      ctypes.c_uint, 3),
              ("dst_sel_y",      ctypes.c_uint, 3),
              ("dst_sel_z",      ctypes.c_uint, 3),
              ("dst_sel_w",      ctypes.c_uint, 3),
              ("format",         ctypes.c_uint, 7),
              ("_unusedA",       ctypes.c_uint, 2),
              ("index_stride",   ctypes.c_uint, 2),
              ("add_tid_enable", ctypes.c_uint, 1),
              ("resource_level", ctypes.c_uint, 1),
              ("_unusedB",       ctypes.c_uint, 1),
              ("LLC_noalloc",    ctypes.c_uint, 2),
              ("oob_select",     ctypes.c_uint, 2),
              ("type",           ctypes.c_uint, 2)]


  @classmethod
  def default(cls):
    return cls(format         = 4,
               resource_level = 1,
               oob_select     = 3)


class SrdUpperValue10XX(BitfieldUnion):
  _fields_ = [("fields", SrdUpperFields10XX), ("value", ctypes.c_uint32)]

  @classmethod
  def default(cls):
    return cls(fields=SrdUpperFields10XX.default())


class SrdUpperFields11XX(BitfieldStructure):
  _fields_ = [("dst_sel_x",      ctypes.c_uint, 3),
              ("dst_sel_y",      ctypes.c_uint, 3),
              ("dst_sel_z",      ctypes.c_uint, 3),
              ("dst_sel_w",      ctypes.c_uint, 3),
              ("format",         ctypes.c_uint, 7),
              ("_unusedA",       ctypes.c_uint, 2),
              ("index_stride",   ctypes.c_uint, 2),
              ("add_tid_enable", ctypes.c_uint, 1),
              ("resource_level", ctypes.c_uint, 1),
              ("_unusedB",       ctypes.c_uint, 1),
              ("LLC_noalloc",    ctypes.c_uint, 2),
              ("oob_select",     ctypes.c_uint, 2),
              ("type",           ctypes.c_uint, 2)]


  @classmethod
  def default(cls):
    return cls(format         = 4,
               resource_level = 1,
               oob_select     = 3)


class SrdUpperValue11XX(BitfieldUnion):
  _fields_ = [("fields", SrdUpperFields11XX), ("value", ctypes.c_uint32)]

  @classmethod
  def default(cls):
    return cls(fields=SrdUpperFields11XX.default())


def SrdUpperValue(isa):
  if isa[0] == 11:
    return SrdUpperValue11XX.default()
  elif isa[0] == 10:
    return SrdUpperValue10XX.default()
  else:
    return SrdUpperValue9XX.default()



class OpTemplate(Module):
    """
    Base template for high level operator (mem/alu), template contain data and code
    section for implementing high level operator;
    resources required for high level operator are already accounted in main parts
    kernel section

    Usage: high level operator like unary,binary operators opearting on tensor dimension or
           memory operator that stores/loads tensor from near/far memory

    Initially monolithic code segments doing high level operator  vpgr/sgpr (temp ones ) are placeholders
    must be replaced when its actually placed in main kernel


    """

    ## constructor
    def __init__(self, name=""):
      self.name     = name
      ## list order of operations
      ## Module key "LaddrCalcA", "lrda", "lwra", "StoreC", "loadC",
      ## order of code is important
      self.itemList = []   ## list of Code Modules
      self.tmpSgpr  = None
      self.tmpVgpr  = None

    def __str__(self):
      s = ""
      if printModuleNames:
        s += "// %s { \n" % self.name
      s += "".join([str(x) for x in self.itemList])
      if printModuleNames:
        s += "// } %s\n" % self.name
      return s

    def findNamedCode(self, targetName):
      return next((Moditem for Moditem in self.itemList if Moditem.name==targetName), None)

    def addModule(self, ModItem):
      """
      Add specified Code modules to the list of Modules in the opTemplate
      ModItem MUST be a Module, list of instructions not string
      returns Module to facilitate one-line create/add patterns
      """
      if isinstance(ModItem,Module):
        #self.itemList.append(ModItem)
        self.itemList.extend(ModItem.itemList)
      else:
        assert 0, "unknown ModItem type (%s) for OpTemplate.addCode. Moditem=%s"%(type(ModItem), ModItem)
      return ModItem

      def addTempSgpr(self, sgpr):
        self.tmpSgpr = sgpr

      def addTempVgpr(self, vgpr):
        self.tmpVgpr = vgpr

class MemOpTemplate(OpTemplate):
    """
    template for local/global data movement code sections
    list should have sequence of code modules supporting data movement,
    including offset calculation , offset increment, load/store

    current code sections are expected to follow program consistency (no out of order in scheduling them)

    This needs further refinement- handling temp registers in code
    temporary register(s) used at the time of code generation(S) need to be replaced when its called
    temp register in instruction should use _sgpr%len_  or _vgpr%len_  len determines number of temp register

    before using code , allocate number of registers required for code

    """
    def __init__(self, name=""):
      self.name = name
      self.itemList = []   ## list of  COde Modules
      self.tmpSgpr  = None
      self.tmpVgpr  = None
