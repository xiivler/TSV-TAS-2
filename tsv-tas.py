import math
import struct
import enum
import sys
from ftplib import FTP
import json
import re
import csv
from dataclasses import dataclass, field

#default gyroscope rotation is 3x3 identity matrix

ANG_VEL_FACTOR = -3/200.0

ftp = False
debug = False
nxtas = False
remove_empty = False #won't work for lunakit/exlaunch format until mod treats y accel as -1

if (sys.argv[1][0] == '-'):
    options = sys.argv[1]
    infile = sys.argv[2]
    outfile = sys.argv[3]
    ftp = "f" in options
    debug = "d" in options
    nxtas = "n" in options
    remove_empty = "e" in options

else:
    infile = sys.argv[1]
    outfile = sys.argv[2]

stage_name = ""
entrance = ""
scenario = 1

independent_gyro = False #if True, can set angular velocity independently of rotation, if False angular velocity calculated from rotation
delayed_motion = False #if True, moves all motion macros 1f earlier

@dataclass
class Vector2f:
    x: float
    y: float

    @staticmethod
    def zero():
        return Vector2f(0, 0)


@dataclass
class Vector3f:
    x: float
    y: float
    z: float

    @staticmethod
    def zero():
        return Vector3f(0, 0, 0)

    @staticmethod
    def default_accel():
        #return Vector3f(0, -1, 0)
        return Vector3f(0, 0, 0)
    
@dataclass
class Joystick:
    r: float
    theta: float
    x: float
    y: float

    @staticmethod
    def zero():
        return Joystick(0, 0, 0, 0)
    
    @staticmethod
    def polar(r_theta): #accepts pair with r and theta, snaps to nearest 2^16-representable float
        r = r_theta[0]
        theta = r_theta[1]
        return Joystick(r, theta, int(32767 * r * math.cos(math.radians(theta))) / 32767.0, int(32767 * r * math.sin(math.radians(theta))) / 32767.0)

@dataclass
class Matrix33f:
    xx: float
    xy: float
    xz: float
    yx: float
    yy: float
    yz: float
    zx: float
    zy: float
    zz: float

    @staticmethod
    def ident():
        return Matrix33f(1, 0, 0,
                         0, 1, 0,
                         0, 0, 1)


@dataclass
class Gyro:
    euler: Vector3f
    direction: Matrix33f
    ang_vel: Vector3f

    @staticmethod
    def zero():
        return Gyro(Vector3f.zero(), Matrix33f.ident(), Vector3f.zero())


@dataclass
class Frame:
    step: int
    second_player: bool
    buttons: int
    buttonsOn: int
    buttonsOff: int
    left_stick: Joystick
    right_stick: Joystick
    accel_left: Vector3f
    accel_right: Vector3f
    gyro_left: Gyro
    gyro_right: Gyro
    macro: bool

    def toStrArray(self):
        dl = self.gyro_left.direction
        dr = self.gyro_right.direction
        avl = self.gyro_left.ang_vel
        avr = self.gyro_right.ang_vel
        values = [self.step, self.buttons, self.buttonsOn, self.buttonsOff, self.left_stick.r, self.left_stick.theta, self.left_stick.x, self.left_stick.y, self.right_stick.r, self.right_stick.theta, self.right_stick.x, self.right_stick.y,
        self.accel_left.x, self.accel_left.y, self.accel_left.z, self.accel_right.x, self.accel_right.y, self.accel_right.z,
        dl.xx, dl.xy, dl.xz, dl.yx, dl.yy, dl.yz, dl.zx, dl.zy, dl.zz, avl.x, avl.y, avl.z,
        dr.xx, dr.xy, dr.xz, dr.yx, dr.yy, dr.yz, dr.zx, dr.zy, dr.zz, avr.x, avr.y, avr.z]
        return map(str, values)


@dataclass
class Script:
    change_stage_name:str
    change_stage_id:str
    scenario_no:int
    frame_count:int
    is_two_player:bool
    startPosition:Vector3f
    frames:list[Frame] = field(default_factory=list)


class Button(enum.Enum):
    cPadIdx_A = 0,
    cPadIdx_B = 1,
    cPadIdx_C = 2,
    cPadIdx_X = 3,
    cPadIdx_Y = 4,
    cPadIdx_Z = 5,
    cPadIdx_2 = 6, # R Stick Click
    cPadIdx_1 = 7, # L Stick Click
    cPadIdx_Home = 8,
    cPadIdx_Minus = 9,
    cPadIdx_Plus = 10,
    cPadIdx_Start = 11,
    cPadIdx_Select = 12,
    cPadIdx_ZL = 2,
    cPadIdx_ZR = 5,
    cPadIdx_L = 13,
    cPadIdx_R = 14,
    cPadIdx_Touch = 15,
    cPadIdx_Up = 16,
    cPadIdx_Down = 17,
    cPadIdx_Left = 18,
    cPadIdx_Right = 19,
    cPadIdx_LeftStickUp = 20,
    cPadIdx_LeftStickDown = 21,
    cPadIdx_LeftStickLeft = 22,
    cPadIdx_LeftStickRight = 23,
    cPadIdx_rightUp = 24,
    cPadIdx_rightDown = 25,
    cPadIdx_rightLeft = 26,
    cPadIdx_rightRight = 27,
    cPadIdx_Max = 28

def to_f2(f4): #stores float with 2 byte precision if uncommented
    #return int(f4 * 32767) / 32767.0
    return f4

def getButtonBin(button):
    button = button.lower().strip()
    if button == "a": return 2**Button.cPadIdx_A.value[0]
    elif button == "b": return 2**Button.cPadIdx_B.value[0]
    elif button == "x": return 2**Button.cPadIdx_X.value[0]
    elif button == "y": return 2**Button.cPadIdx_Y.value[0]
    elif button == "l": return 2**Button.cPadIdx_L.value[0]
    elif button == "r": return 2**Button.cPadIdx_R.value[0]
    elif button == "zl": return 2**Button.cPadIdx_ZL.value[0]
    elif button == "zr": return 2**Button.cPadIdx_ZR.value[0]
    elif button == "plus" or button == "+": return 2**Button.cPadIdx_Plus.value[0]
    elif button == "minus" or button == "-": return 2**Button.cPadIdx_Minus.value[0]
    elif button == "dp-l": return 2**Button.cPadIdx_Left.value[0]
    elif button == "dp-u": return 2**Button.cPadIdx_Up.value[0]
    elif button == "dp-r": return 2**Button.cPadIdx_Right.value[0]
    elif button == "dp-d": return 2**Button.cPadIdx_Down.value[0]
    elif button == "ls": return 2**Button.cPadIdx_1.value[0]
    elif button == "rs": return 2**Button.cPadIdx_2.value[0]
    else: return 0 #no button found
    
def nxTAS_Buttons(buttons): #converts button int into string list of buttons for nx-TAS format
    button_list = []
    if buttons == 0: return "NONE"
    if buttons & 2**Button.cPadIdx_A.value[0]: button_list.append("KEY_A")
    if buttons & 2**Button.cPadIdx_B.value[0]: button_list.append("KEY_B")
    if buttons & 2**Button.cPadIdx_X.value[0]: button_list.append("KEY_X")
    if buttons & 2**Button.cPadIdx_Y.value[0]: button_list.append("KEY_Y")
    if buttons & 2**Button.cPadIdx_L.value[0]: button_list.append("KEY_L")
    if buttons & 2**Button.cPadIdx_R.value[0]: button_list.append("KEY_R")
    if buttons & 2**Button.cPadIdx_ZL.value[0]: button_list.append("KEY_ZL")
    if buttons & 2**Button.cPadIdx_ZR.value[0]: button_list.append("KEY_ZR")
    if buttons & 2**Button.cPadIdx_Plus.value[0]: button_list.append("KEY_PLUS")
    if buttons & 2**Button.cPadIdx_Minus.value[0]: button_list.append("KEY_MINUS")
    if buttons & 2**Button.cPadIdx_Left.value[0]: button_list.append("KEY_DLEFT")
    if buttons & 2**Button.cPadIdx_Right.value[0]: button_list.append("KEY_DRIGHT")
    if buttons & 2**Button.cPadIdx_Up.value[0]: button_list.append("KEY_DUP")
    if buttons & 2**Button.cPadIdx_Down.value[0]: button_list.append("KEY_DDOWN")
    if buttons & 2**Button.cPadIdx_1.value[0]: button_list.append("KEY_LSTICK")
    if buttons & 2**Button.cPadIdx_2.value[0]: button_list.append("KEY_RSTICK")

    return ";".join(button_list)

def prepareToken(token, first_column, row_duration):
    return evaluateMath(evaluateVariables(token, row_duration), first_column)

def evaluateVariables(token, row_duration): #evaluates all variables of form $ or #
    while match_obj := re.search("\\$\\w+", token): #replace variables with their values
        try:
            token = token.replace(match_obj.group(), vars.get(match_obj.group().lower()[1:]))
        except:
            print("Variable " + match_obj.group() + " not found")
            quit(-1)

    token = token.replace('#', str(row_duration))

    return token.lower()


def evaluateMath(token, whole_token): #evaluates math expressions
    if whole_token: #match math expressions that take up the whole token
        math_regex = "^(([0-9,\\. \\+\\*\\-\\(\\)])+([\\+\\*\\-])([0-9,\\. \\+\\*\\-\\(\\)])+)$"
        group = 1
    else: #match math expressions that begin/end with parentheses, commas, brackets, or semicolons
        math_regex = "([\\(\\,\\;\\[])(([0-9,\\. \\+\\*\\-\\(\\)])+([\\+\\*\\-])([0-9,\\. \\+\\*\\-\\(\\)])+)([\\)\\,\\;\\]])"
        group = 2
    # print("token before search: " + token)
    while match_obj := re.search(math_regex, token): #evaluate math operations
        #print(match_obj.group(group))
        #print(eval(match_obj.group(group)))
        token = token.replace(match_obj.group(group), str(eval(match_obj.group(group))))

    return token.lower()

def evaluateLast(token, prev): #replaces any ! marks with prev, then calls evaluateMath
    token = token.replace('!', str(prev))
    # print("Replaced token: " + token)
    return evaluateMath(token, True)

def evaluateCurrentFrame(token, offset): #replaces any @ marks with offset, then calls evaluateMath
    token = token.replace('@', str(offset))
    # print("Replaced token: " + token)
    return evaluateMath(token, True)

#parses the duration of a token
def parseDuration(token, default):
    try:
        duration_str = token[token.index('[') + 1 : token.index(']')].strip()
        if duration_str == '?' or duration_str == '*': #special duration characters
            duration = duration_str
        else:
            duration = int(duration_str)
        token = token.replace(token[token.index('[') : token.index(']') + 1], '')
        return token.strip(), duration
    except:
        return token, default

#prev_frame is used to evaluate ! characters if it is not None
#offset_from_row_index is used to evaluate @ characters if it is not None
def getStickPolar(token, right_stick, prev_frame, offset_from_row_index):
    r = 1.0
    theta = 0.0
    if prev_frame is not None: #contains !
        if right_stick: prev_stick = prev_frame.right_stick
        else: prev_stick = prev_frame.left_stick
    if ';' in token: #(r; theta)
        r_token = token[0:token.index(';')]
        theta_token = token[token.index(';') + 1:]
        if prev_frame is not None: r_token, theta_token = evaluateLast(r_token, prev_stick.r), evaluateLast(theta_token, prev_stick.theta)
        if offset_from_row_index is not None: r_token, theta_token = evaluateCurrentFrame(r_token, offset_from_row_index), evaluateCurrentFrame(theta_token, offset_from_row_index)
        r, theta = float(r_token), float(theta_token)
    else:# (r)
        if prev_frame is not None: token = evaluateLast(token, prev_stick.theta)
        if offset_from_row_index is not None: token = evaluateCurrentFrame(token, offset_from_row_index)
        theta = float(token)
    return r, theta

#euler in degrees to rotation matrix
def toRotationMatrix(euler:Vector3f):
    euler_radians = Vector3f.zero()
    euler_radians.x, euler_radians.y, euler_radians.z = math.radians(euler.x), math.radians(euler.y), math.radians(euler.z)

    cx = math.cos(euler_radians.x)
    cy = math.cos(euler_radians.y)
    cz = math.cos(euler_radians.z)
    sx = math.sin(euler_radians.x)
    sy = math.sin(euler_radians.y)
    sz = math.sin(euler_radians.z)
    
    return Matrix33f(to_f2(cy * cz), to_f2(-cy * sz), to_f2(sy), 
                                to_f2(cz * sx * sy + cx * sz), to_f2(cx * cz - sx * sy * sz), to_f2(-cy * sx),
                                to_f2(-cx * cz * sy + sx * sz), to_f2(cz * sx + cx * sy * sz), to_f2(cx * cy))

def getGyroValues(token):
    all = token.split(";") #(pitch; yaw; roll) or #(pitch; yaw; roll; ang-x; ang-y; ang-z)
    ang_vel = Vector3f.zero()
    euler = Vector3f.zero()
    if len(all) == 6:
        ang_vel.x, ang_vel.y, ang_vel.z = to_f2(float(all[3])), to_f2(float(all[4])), to_f2(float(all[5]))
    euler.x, euler.y, euler.z = float(all[0]), float(all[1]), float(all[2])
    
    return Gyro(euler, toRotationMatrix(euler), ang_vel)

#parses token into subtokens
def parseToken(token, indexWrite, duration, rowIndex, rowDuration):
    print("Parsing: " + token)
    print("Write Index: " + str(indexWrite))
    
    token = token.strip()
    if re.search("^\\[[0-9]*\\] *\\(", token) or (not "|" in token and not "/" in token):
        token, duration = parseDuration(token, duration) #see if there is a duration associated with the token
    
    print("Duration: " + str(duration))

    if len(token) > 0 and token[0] == '(' and token[-1] == ')': token = token[1 : -1] #remove enclosing parentheses

    if "|" in token: parseSequence(token, indexWrite, rowIndex, rowDuration)
    elif "/" in token: parseLoop(token, indexWrite, duration, rowIndex)
    elif "->" in token: parseInterpolatedStick(token, indexWrite, duration)
    else:
        if duration == "?": print("? duration only allowed within sequences")
        elif duration == "*": addToggle(token, indexWrite, True)
        elif duration == 0: addToggle(token, indexWrite, False)
        elif duration > 0: addToFrameRange(token, range(indexWrite, indexWrite + duration), rowIndex)
        else: addToFrameRange(token, range(indexWrite - 1, indexWrite + duration - 1, -1), rowIndex)

def parseInterpolatedStick(token, indexStart, duration):
    if '@' in token:
        print("Stick interpolation on line " + str(lineInNumber) + " cannot use @ symbol")
        quit(-1)
    if duration < 0:
        print("Stick interpolation on line " + str(lineInNumber) + " cannot have negative duration")
        quit(-1)
    if duration < 2:
        print("Stick interpolation on line " + str(lineInNumber) + " must have duration of at least 2")
        quit(-1)

    indexStop = indexStart + duration

    if indexStart - 1 < 0: prev_frame = blankFrame
    else: prev_frame = script.frames[indexStart - 1]
    
    try:
        token1, token2 = token.split("->")

        right = False #True if right stick/gyro/etc., False if left
        if "r" in token1:
            right = True
        
        token1 = token1[token1.index('(') + 1:token1.index(')')]
        token2 = token2[token2.index('(') + 1:token2.index(')')]

        r1, theta1 = getStickPolar(token1, right, prev_frame)
        r2, theta2 = getStickPolar(token2, right, prev_frame)

        dr = (r2 - r1) / (duration - 1)
        dtheta = (theta2 - theta1) / (duration - 1)

        r, theta = r1, theta1

        for i in range(indexStart, indexStop):
            if right: script.frames[i].right_stick = Joystick.polar((r, theta))
            else: script.frames[i].left_stick = Joystick.polar((r, theta))
            r += dr
            theta += dtheta
        if right: script.frames[indexStop - 1].right_stick = Joystick.polar((r2, theta2))
        else: script.frames[indexStop - 1].left_stick = Joystick.polar((r2, theta2))
    except Exception as e:
        print("Syntax error(s) on line " + str(lineInNumber) + " prevented script generation")
        if debug: print(e)
        quit(-1)

def parseSequence(token, indexWrite, rowIndex, rowDuration):
    steps = token.split('|')
    for i in range(len(steps)):
        subtoken, duration = parseDuration(steps[i], 1) #parse out duration
        if duration == '*':
            print("* not supported for durations within sequences (line " + str(lineInNumber) + ")")
        elif duration == '?':
            print("row duration: " + str(rowDuration))
            duration = rowDuration + rowIndex - indexWrite
            if duration < 0: duration = 0
        parseToken(subtoken, indexWrite, duration, rowIndex, rowDuration)
        indexWrite += duration

def parseLoop(token, indexWrite, duration, rowIndex, rowDuration):
    if duration == '*' or duration == '?':
            print(duration + " not supported for durations within sequences (line " + str(lineInNumber) + ")")
    elif duration == 0:
        return
    elif duration < 0:
        print("Loop on line " + str(lineInNumber) + " cannot have negative total duration")
        quit(-1)

    remainingDuration = duration
    steps = token.split('/')
    subtokens = []
    durations = []
    for i in range(len(steps)):
        subtoken, duration = parseDuration(steps[i], 1) #parse out duration
        subtokens.append(subtoken)
        durations.append(duration)
    while remainingDuration > 0:
        for i in range(len(steps)):
            if remainingDuration <= 0: return
            if durations[i] >= 0:
                parseToken(subtokens[i], indexWrite, min(durations[i], remainingDuration), rowIndex, rowDuration)
                remainingDuration -= durations[i]
            else:
                print("Negative durations are not permitted within loops")
                quit(-1)
            indexWrite += durations[i]


def addToFrameRange(token, frameRange:range, rowIndex):
    #first find start and end frames involved, add any additional frames as needed
    minFrame = maxFrame = 0
    for j in frameRange:
        if j > maxFrame: maxFrame = j
        if j < minFrame: minFrame = j
    for j in range(len(script.frames), maxFrame + 1):
        script.frames.append(Frame(j, False, 0, 0, 0, Joystick.zero(), Joystick.zero(), Vector3f.default_accel(), Vector3f.default_accel(), Gyro.zero(), Gyro.zero(), False))

    if frameRange.start < 0 or frameRange.stop < -1:
        print("Negative durations cannot go before frame 0")
        quit(-1) 
    
    #try:
    if "(" in token: #stick/motion
        right = True #True if right stick/gyro/etc.
        left = True #True if left stick/gyro/etc.
        if "r" in token:
            left = False
        if "l" in token:
            right = False
        prefix = token[0:token.index('(')]
        token = token[token.index('(') + 1:token.index(')')]  

        if "s" in prefix: #stick
            previous_input_symbol = '!' in token
            current_symbol = '@' in token
            if previous_input_symbol or current_symbol: #need to calculate each frame individually
                for j in frameRange:
                    if previous_input_symbol:
                        if j - 1 < 0: prev_frame = blankFrame
                        else: prev_frame = script.frames[j - 1]
                    else:
                        prev_frame = None
                    coords = Joystick.polar(getStickPolar(token, right, prev_frame, j - rowIndex))
                    if right: script.frames[j].right_stick = coords
                    if left: script.frames[j].left_stick = coords
            else:
                polar_coords = getStickPolar(token, right, None, None)
                coords = Joystick.polar(polar_coords)

                for j in frameRange:
                    if right: script.frames[j].right_stick = coords
                    if left: script.frames[j].left_stick = coords
        
        elif "a" in prefix: #accelerometer
            accel = Vector3f(*map(to_f2, map(float, token.split(";"))))

            for j in frameRange:
                if right: script.frames[j].accel_right = accel
                if left: script.frames[j].accel_left = accel
        
        elif "g" in prefix: #gyroscope
            gyro = getGyroValues(token)

            for j in frameRange:
                if right: script.frames[j].gyro_right = gyro
                if left: script.frames[j].gyro_left = gyro

    elif "m" in token: #motion macros
        if delayed_motion: #shift backward by 1
            newStart = frameRange.start - 1
            while newStart < 0: newStart += frameRange.step
            newStop = max(frameRange.stop - 1, -1)
            frameRange = range(newStart, newStop, frameRange.step)

        if not nxtas:
            accel_left = Vector3f.default_accel()
            accel_right = Vector3f.default_accel()
            gyro_left = Gyro.zero()
            gyro_right = Gyro.zero()
            if token == "m" or token == "m-u":
                accel_left = Vector3f(0, 3, 0)
                gyro_left.ang_vel = Vector3f(-3, 0, 0)
            elif token == "m-d":
                accel_left = Vector3f(0, 3, 0)
                gyro_left.ang_vel = Vector3f(3, 0, 0)
            elif token == "m-l":
                accel_left = Vector3f(-3, 0, 0)
                gyro_left.ang_vel = Vector3f(0, 2, 0)
            elif token == "m-r":
                accel_left = Vector3f(3, 0, 0)
                gyro_left.ang_vel = Vector3f(0, -2, 0)
            elif token == "m-uu":
                accel_left = accel_right = Vector3f(0, 3, 0)
                gyro_left.ang_vel = gyro_right.ang_vel = Vector3f(-2, 0, 0)
            elif token == "m-dd":
                accel_left = accel_right = Vector3f(0, 3, 0)
                gyro_left.ang_vel = gyro_right.ang_vel = Vector3f(2, 0, 0)
            elif token == "m-ll":
                accel_left = accel_right = Vector3f(-3, 0, 0)
                gyro_left.ang_vel = gyro_right.ang_vel = Vector3f(0, 2, 0)
            elif token == "m-rr":
                accel_left = accel_right = Vector3f(3, 0, 0)
                gyro_left.ang_vel = gyro_right.ang_vel = Vector3f(0, -2, 0)
            else:
                return
            
            for j in frameRange:
                script.frames[j].accel_left, script.frames[j].accel_right = accel_left, accel_right
                script.frames[j].gyro_left, script.frames[j].gyro_right = gyro_left, gyro_right
                script.frames[j].macro = True
        
        else: #nx-tas motion keybinds
            l_button = False
            if token == "m": l_button = True
            elif token == "m-u":
                l_button = True
                token = "dp-u"
            elif token == "m-d":
                l_button = True
                token = "dp-d"
            elif token == "m-l":
                l_button = True
                token = "dp-l"
            elif token == "m-r":
                l_button = True
                token = "dp-r"
            elif token == "m-uu": token = "dp-u"
            elif token == "m-dd": token = "dp-d"
            elif token == "m-ll": token = "dp-l"
            elif token == "m-rr": token = "dp-r"
            else:
                return

            if l_button:
                for j in frameRange:
                    script.frames[j].buttons |= 2**Button.cPadIdx_L.value[0]

            #include dpad button
            button_bin = getButtonBin(token)
            for j in frameRange:
                script.frames[j].buttons |= button_bin


    else: #button or comment/invalid
        button_bin = getButtonBin(token)         
        for j in frameRange:
            script.frames[j].buttons |= button_bin

    #except Exception as e:
    #    print("Syntax error(s) on line " + str(lineInNumber) + " prevented script generation")
    #    if debug: print(e)
    #    quit(-1)

#add a toggle for a button to be on indefinitely until its next input in the script ([*]) or a toggle to switch such a button off ([0]) – but the program will actually fill in the frames later
def addToggle(token, indexWrite, on):
    try:
        button_bin = getButtonBin(token)  
        if on: script.frames[indexWrite].buttonsOn |= button_bin
        else: script.frames[indexWrite].buttonsOff |= button_bin
    except Exception as e:
        print("Syntax error(s) on line " + str(lineInNumber) + " prevented script generation")
        if debug: print(e)
        quit(-1)

blankFrame = Frame(0, False, 0, 0, 0, Joystick.zero(), Joystick.zero(), Vector3f.default_accel(), Vector3f.default_accel(), Gyro.zero(), Gyro.zero(), False)
stage_name = ""
entrance = ""
scenario = 1
is_two_player = False

script = Script(stage_name, entrance, scenario, -1, False, Vector3f.zero())

script.frame_count = 0

lineInNumber = 1

#count frames
with open(infile) as f:
    for lineIn in f:
        duration = 1
        first = lineIn.split('\t')[0]
        try:duration = int(first)
        except:
            if first == '':
                pass
            else:
                continue
        script.frame_count += duration
    f.close()

script.frames = [Frame(i, False, 0, 0, 0, Joystick.zero(), Joystick.zero(), Vector3f.default_accel(), Vector3f.default_accel(), Gyro.zero(), Gyro.zero(), False) for i in range(script.frame_count)]

indexStart = 0
indexStop = 0

vars = dict()

with open(infile) as f:
    prevLineInDuration = 1
    for lineIn in f:
        print(lineIn)
        lineIn = lineIn.split('\t')
        lineIn[-1] = lineIn[-1].strip()
        #handle first token (duration or variable assignment)
        lineInDuration = 1
        first = lineIn[0].strip()
        try: lineInDuration = int(first)
        except:
            if first == '':
                pass
            elif first[0] == '$': #variables
                if '=' in first: #variable assignment
                    var = first[1:first.index('=')].strip().lower()
                    value = first[first.index('=') + 1:].strip()

                    #script start variables
                    if var == 'stage':
                        script.change_stage_name = value
                    elif var == 'entr' or var == 'entrance':
                        script.change_stage_id = value
                    elif var == 'scen' or var == 'scenario':
                        try: script.scenario_no = int(value)
                        except:
                            print("Invalid scenario number")
                            quit(-1)
                    elif var == 'independent_gyro' or var == 'ind_gyro':
                        if value.lower() == 'true' or value.lower() == 't':
                            independent_gyro = True
                    elif var == 'pos' or var == 'position':
                        value = value[value.index('(') + 1:value.index(')')]
                        coords = value.split(';')
                        script.startPosition.x = float(coords[0])
                        script.startPosition.y = float(coords[1])
                        script.startPosition.z = float(coords[2])
                    elif var == 'delayed_motion':
                        if value.lower() == 'true' or value.lower() == 't':
                            delayed_motion = True

                    #other variables
                    else:
                        value = prepareToken(value, True, 0)
                        vars.update({var: value})
                    lineInNumber += 1
                    continue
                else:
                    try:
                        lineInDuration = int(evaluateLast(prepareToken(first, True, 0), prevLineInDuration))
                    except:
                        lineInNumber += 1
                        continue
            else:
                try:
                    print(first)
                    lineInDuration = int(evaluateLast(first, prevLineInDuration))
                except:
                    lineInNumber += 1
                    continue
        
        for i in range(1, len(lineIn)):
            if lineIn[i] == '':
                continue

            #perform all variable evaluation and as much math evaluation as possible
            token = prepareToken(lineIn[i], False, lineInDuration)

            """ for i in range(script.frame_count, indexStop):
                script.frames.append(Frame(i, False, 0, Vector2f.zero(), Vector2f.zero(), Vector3f.zero(), Vector3f.zero(), Gyro.zero(), Gyro.zero(), False))
            script.frame_count = len(script.frames) """

            print("Line duration: " + str(lineInDuration))
            parseToken(token, indexStart, lineInDuration, indexStart, lineInDuration)

        indexStart += lineInDuration
        lineInNumber += 1
        prevLineInDuration = lineInDuration

    # now that all the inputs have been parsed, go through again to process toggled buttons
    buttonsOn = 0
    for frame in script.frames:
        buttonsOn |= frame.buttonsOn
        buttonsOff = frame.buttons | frame.buttonsOff
        buttonsOn &= ~buttonsOff
        frame.buttons |= buttonsOn

    # blankFrame = Frame(0, False, 0, Joystick.zero(), Joystick.zero(), Vector3f.default_accel(), Vector3f.default_accel(), Gyro.zero(), Gyro.zero(), False)

    #calculate angular velocity if gyroscope and angular velocity are not independent, or calculate proper gyroscope if a motion macro is used
    #angular velocity is change in gyroscope in degrees times -3/400
    if not independent_gyro:
        euler_left_old, euler_right_old = script.frames[0].gyro_left.euler, script.frames[0].gyro_right.euler 
        for i in range(1, script.frame_count):
            euler_left, euler_right = script.frames[i].gyro_left.euler, script.frames[i].gyro_right.euler
            if not script.frames[i].macro:
                script.frames[i].gyro_left.ang_vel = Vector3f(ANG_VEL_FACTOR*(euler_left.x - euler_left_old.x), ANG_VEL_FACTOR*(euler_left.y - euler_left_old.y), ANG_VEL_FACTOR*(euler_left.z - euler_left_old.z))
                script.frames[i].gyro_right.ang_vel = Vector3f(ANG_VEL_FACTOR*(euler_right.x - euler_right_old.x), ANG_VEL_FACTOR*(euler_right.y - euler_right_old.y), ANG_VEL_FACTOR*(euler_right.z - euler_right_old.z))
            '''
            else:
                ang_vel_left, ang_vel_right = script.frames[i].gyro_left.ang_vel, script.frames[i].gyro_right.ang_vel
                script.frames[i].gyro_left.euler = Vector3f(euler_left_old.x + ang_vel_left.x / ANG_VEL_FACTOR, euler_left_old.y + ang_vel_left.y / ANG_VEL_FACTOR, euler_left_old.z + ang_vel_left.z / ANG_VEL_FACTOR)
                script.frames[i].gyro_right.euler = Vector3f(euler_right_old.x + ang_vel_right.x / ANG_VEL_FACTOR, euler_right_old.y + ang_vel_right.y / ANG_VEL_FACTOR, euler_right_old.z + ang_vel_right.z / ANG_VEL_FACTOR)
                script.frames[i].gyro_left.direction = toRotationMatrix(script.frames[i].gyro_left.euler)
                script.frames[i].gyro_right.direction = toRotationMatrix(script.frames[i].gyro_right.euler)
            '''
            euler_left_old, euler_right_old = euler_left, euler_right

    #remove empty frames
    if (remove_empty):
        for i in range(script.frame_count - 1, -1, -1):
            blankFrame.step = i
            if blankFrame == script.frames[i]:
                del script.frames[i]

if debug:
    debugFile = open(outfile + "-debug.csv", "w")

    debugFile.write("Frame,Buttons,ButtonsOn,ButtonsOff,lx.r,ls.theta,ls.x,ls.y,rs.x,rs.y,la.x,la.y,la.z,ra.x,ra.y,ra.z,lg.r.xx,lg.r.xy,lg.r.xz,lg.r.yx,lg.r.yy,lg.r.yz,lg.r.zx,lg.r.zy,lg.r.zz,lg.v.x,lg.v.y,lg.v.z,rg.r.xx,rg.r.xy,rg.r.xz,rg.r.yx,rg.r.yy,rg.r.yz,rg.r.zx,rg.r.zy,rg.r.zz,rg.v.x,rg.v.y,rg.v.z\n")
    for i in range(len(script.frames)):
        csv_writer = csv.writer(debugFile, delimiter = ',')
        data = script.frames[i].toStrArray()
        csv_writer.writerow(data)
    debugFile.close()

if nxtas:
    outf = open(outfile, "w")
    for frame in script.frames:
        outf.write(str(frame.step) + " " + nxTAS_Buttons(frame.buttons) + " "
                   + str(int(frame.left_stick.x * 32767)) + ";" + str(int(frame.left_stick.y * 32767)) + " "
                   + str(int(frame.right_stick.x * 32767)) + ";" + str(int(frame.right_stick.y * 32767)) + '\n')

else:
    outf = open(outfile, "wb")
    outf.write(b"BOOB")
    outf.write(struct.pack("<I?3xi", len(script.frames), is_two_player, script.scenario_no))
    outf.write(bytes(script.change_stage_name, encoding="ascii") + b'\0'*(128-len(script.change_stage_name)))
    outf.write(bytes(script.change_stage_id, encoding="ascii") + b'\0'*(128-len(script.change_stage_id)))
    outf.write(struct.pack("<3f", script.startPosition.x, script.startPosition.y, script.startPosition.z))

    for frame in script.frames:
        outf.write(struct.pack("<I?3xI", frame.step, frame.second_player, frame.buttons))
        outf.write(struct.pack("<2f", frame.left_stick.x, frame.left_stick.y))
        outf.write(struct.pack("<2f", frame.right_stick.x, frame.right_stick.y))
        outf.write(struct.pack("<3f", frame.accel_left.x, frame.accel_left.y, frame.accel_left.z))
        outf.write(struct.pack("<3f", frame.accel_right.x, frame.accel_right.y, frame.accel_right.z))
        outf.write(struct.pack("<9f", frame.gyro_left.direction.xx, frame.gyro_left.direction.xy, frame.gyro_left.direction.xz, frame.gyro_left.direction.yx, frame.gyro_left.direction.yy, frame.gyro_left.direction.yz, frame.gyro_left.direction.zx, frame.gyro_left.direction.zy, frame.gyro_left.direction.zz))
        outf.write(struct.pack("<3f", frame.gyro_left.ang_vel.x, frame.gyro_left.ang_vel.y, frame.gyro_left.ang_vel.z))
        outf.write(struct.pack("<9f", frame.gyro_right.direction.xx, frame.gyro_right.direction.xy, frame.gyro_right.direction.xz, frame.gyro_right.direction.yx, frame.gyro_right.direction.yy, frame.gyro_right.direction.yz, frame.gyro_right.direction.zx, frame.gyro_right.direction.zy, frame.gyro_right.direction.zz))
        outf.write(struct.pack("<3f", frame.gyro_right.ang_vel.x, frame.gyro_right.ang_vel.y, frame.gyro_right.ang_vel.z))

outf.close()

print('Script successfully generated')

if ftp:
    ftp_config_file = open('ftp_config.json')
    ftp_config = json.load(ftp_config_file)
    ftp_config_file.close

    ftp = FTP()
    ftp.connect(host=ftp_config['ip'], port=int(ftp_config['port']))
    ftp.login(user=ftp_config['user'],passwd=ftp_config['passwd'])

    file = open(outfile, 'rb')

    result = ftp.storbinary('STOR scripts/' + outfile, file)
    if result == '226 OK':
        print('Script successfully uploaded')
    else:
        print('FTP error')

    ftp.quit()