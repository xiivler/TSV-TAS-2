import math
from pickle import TRUE
import struct
import enum
import sys
from ftplib import FTP
import json
import re
import csv
from dataclasses import dataclass, field
from io import FileIO
from typing import cast

# default gyroscope rotation is 3x3 identity matrix

ANG_VEL_FACTOR = -3 / 200.0

ftp = False
debug = False
nxtas = False
remove_empty = (
    False  # won't work for lunakit/exlaunch format until mod treats y accel as -1
)
same_path = False
loop = False
stas = False

if sys.argv[1][0] == "-":
    options = sys.argv[1]
    ftp = "f" in options
    debug = "d" in options
    nxtas = "n" in options
    remove_empty = "e" in options
    same_path = "p" in options
    loop = "l" in options
    stas = "s" in options
    infile = sys.argv[2]
    if not same_path:
        outfile = sys.argv[3]

else:
    infile = sys.argv[1]
    if not same_path:
        outfile = sys.argv[2]

if infile.endswith(".tsv") or infile.endswith(".txt"):
    separator = "\t"
elif infile.endswith(".csv"):
    separator = ","
else:
    sys.exit("Error: Invalid file type")

if same_path:
    outfile = infile[0 : infile.rindex(".")]
    if nxtas:
        outfile += ".txt"
    elif stas:
        outfile += ".stas"

# if True, can set angular velocity independently of rotation, if False angular velocity calculated from rotation
independent_gyro = False
motion_offset = 0  # shifts motion macros by this amount
ls_offset: float = 0  # shifts left stick inputs by this number of degrees


@dataclass
class Vector2f:
    x: float
    y: float

    @staticmethod
    def zero():
        return Vector2f(0, 0)


@dataclass
class Vector2i:
    x: int
    y: int

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
        # return Vector3f(0, -1, 0)
        return Vector3f(0, 0, 0)


def vec3fNEQ0(vec1: Vector3f) -> bool:
    vec2 = Vector3f.zero()
    if vec1 is None:
        return True
    return not (
        math.isclose(vec1.x, vec2.x)
        and math.isclose(vec1.y, vec2.y)
        and math.isclose(vec1.z, vec2.z)
    )


def vec3fEQ(vec1: Vector3f, vec2: Vector3f) -> bool:
    if vec1 is None and vec2 is None:
        return True
    if vec1 is None or vec2 is None:
        return False
    return (
        math.isclose(vec1.x, vec2.x)
        and math.isclose(vec1.y, vec2.y)
        and math.isclose(vec1.z, vec2.z)
    )


@dataclass
class Quat4f:
    x: float
    y: float
    z: float
    w: float

    @staticmethod
    def unit():
        return Quat4f(0, 0, 0, 0)


@dataclass
class Joystick:
    r: float
    theta: float
    x: int
    y: int

    @staticmethod
    def zero():
        return Joystick(0, 0, 0, 0)

    @staticmethod
    def polar(
        r_theta,
    ):  # accepts pair with r and theta, snaps to nearest 2^16-representable float
        r = r_theta[0]
        theta = r_theta[1]
        return Joystick(
            r,
            theta,
            int(32767 * r * math.cos(math.radians(theta))),
            int(32767 * r * math.sin(math.radians(theta))),
        )

    @staticmethod
    def cartesian(x, y):
        # note that with how polar rounds the r and theta may not generate the x and y
        return Joystick(
            math.sqrt(x**2 + y**2) / 32767, math.degrees(math.atan2(y, x)), x, y
        )

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y


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
        return Matrix33f(1, 0, 0, 0, 1, 0, 0, 0, 1)


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
        values = [
            self.step,
            self.second_player,
            self.buttons,
            self.buttonsOn,
            self.buttonsOff,
            self.left_stick.r,
            self.left_stick.theta,
            self.left_stick.x,
            self.left_stick.y,
            self.right_stick.r,
            self.right_stick.theta,
            self.right_stick.x,
            self.right_stick.y,
            self.accel_left.x,
            self.accel_left.y,
            self.accel_left.z,
            self.accel_right.x,
            self.accel_right.y,
            self.accel_right.z,
            dl.xx,
            dl.xy,
            dl.xz,
            dl.yx,
            dl.yy,
            dl.yz,
            dl.zx,
            dl.zy,
            dl.zz,
            avl.x,
            avl.y,
            avl.z,
            dr.xx,
            dr.xy,
            dr.xz,
            dr.yx,
            dr.yy,
            dr.yz,
            dr.zx,
            dr.zy,
            dr.zz,
            avr.x,
            avr.y,
            avr.z,
            script.commands[self.step],
        ]
        return map(str, values)


@dataclass
class Script:
    change_stage_name: str
    change_stage_id: str
    scenario_no: int
    is_two_player: bool
    startPosition: Vector3f
    frames: list[Frame] = field(default_factory=list)
    frames_P1: list[Frame] = field(default_factory=list)
    frames_P2: list[Frame] = field(default_factory=list)
    commands: list[list[str]] = field(default_factory=list)

    def getFrames(self, player_two):
        if player_two:
            return self.frames_P2
        else:
            return self.frames_P1

    def addFrames(self, end):  # add frames through frame end - 1
        for j in range(len(self.frames_P1), end):
            self.frames_P1.append(
                Frame(
                    j,
                    False,
                    0,
                    0,
                    0,
                    Joystick.zero(),
                    Joystick.zero(),
                    Vector3f.default_accel(),
                    Vector3f.default_accel(),
                    Gyro.zero(),
                    Gyro.zero(),
                    False,
                )
            )
        for j in range(len(self.commands), end):
            self.commands.append([])
        if self.is_two_player:
            for j in range(len(self.frames_P2), end):
                self.frames_P2.append(
                    Frame(
                        j,
                        True,
                        0,
                        0,
                        0,
                        Joystick.zero(),
                        Joystick.zero(),
                        Vector3f.default_accel(),
                        Vector3f.default_accel(),
                        Gyro.zero(),
                        Gyro.zero(),
                        False,
                    )
                )

    # merge player 1 and player 2 frames into one array called frames
    def combineFrames(self):
        if self.is_two_player:
            self.frames = []
            for j in range(0, len(self.frames_P1)):
                self.frames.append(self.frames_P1[j])
                self.frames.append(self.frames_P2[j])
        else:
            self.frames = self.frames_P1


class Button(enum.IntEnum):
    cPadIdx_A = 0
    cPadIdx_B = 1
    cPadIdx_C = 2
    cPadIdx_X = 3
    cPadIdx_Y = 4
    cPadIdx_Z = 5
    cPadIdx_2 = 6  # R Stick Click
    cPadIdx_1 = 7  # L Stick Click
    cPadIdx_Home = 8
    cPadIdx_Minus = 9
    cPadIdx_Plus = 10
    cPadIdx_Start = 11
    cPadIdx_Select = 12
    cPadIdx_ZL = 2
    cPadIdx_ZR = 5
    cPadIdx_L = 13
    cPadIdx_R = 14
    cPadIdx_Touch = 15
    cPadIdx_Up = 16
    cPadIdx_Down = 17
    cPadIdx_Left = 18
    cPadIdx_Right = 19
    cPadIdx_LeftStickUp = 20
    cPadIdx_LeftStickDown = 21
    cPadIdx_LeftStickLeft = 22
    cPadIdx_LeftStickRight = 23
    cPadIdx_rightUp = 24
    cPadIdx_rightDown = 25
    cPadIdx_rightLeft = 26
    cPadIdx_rightRight = 27
    cPadIdx_Max = 28


class STASButton(enum.IntEnum):
    cSTAS_A = 0
    cSTAS_B = 1
    cSTAS_X = 2
    cSTAS_Y = 3
    cSTAS_LeftStick = 4
    cSTAS_RightStick = 5
    cSTAS_L = 6
    cSTAS_R = 7
    cSTAS_ZL = 8
    cSTAS_ZR = 9
    cSTAS_Plus = 10
    cSTAS_Minus = 11
    cSTAS_DLeft = 12
    cSTAS_DUp = 13
    cSTAS_DRight = 14
    cSTAS_DDown = 15


def to_f2(f4):  # stores float with 2 byte precision if uncommented
    # return int(f4 * 32767) / 32767.0
    return f4


def getButtonBin(button: str, stas: bool):
    button = button.lower().strip()
    if len(button) > 1 and button[0] == "c":
        button = button[1:]  # 2P button
    if button == "a":
        return 2 ** (STASButton.cSTAS_A.value if stas else Button.cPadIdx_A.value)

    elif button == "b":
        return 2 ** (STASButton.cSTAS_B.value if stas else Button.cPadIdx_B.value)

    elif button == "x":
        return 2 ** (STASButton.cSTAS_X.value if stas else Button.cPadIdx_X.value)

    elif button == "y":
        return 2 ** (STASButton.cSTAS_Y.value if stas else Button.cPadIdx_Y.value)

    elif button == "l":
        return 2 ** (STASButton.cSTAS_L.value if stas else Button.cPadIdx_L.value)

    elif button == "r":
        return 2 ** (STASButton.cSTAS_R.value if stas else Button.cPadIdx_R.value)

    elif button == "zl":
        return 2 ** (STASButton.cSTAS_ZL.value if stas else Button.cPadIdx_ZL.value)

    elif button == "zr":
        return 2 ** (STASButton.cSTAS_ZR.value if stas else Button.cPadIdx_ZR.value)

    elif button == "plus" or button == "+":
        return 2 ** (STASButton.cSTAS_Plus.value if stas else Button.cPadIdx_Plus.value)

    elif button == "minus" or button == "-":
        return 2 ** (
            STASButton.cSTAS_Minus.value if stas else Button.cPadIdx_Minus.value
        )

    elif button == "dp-l":
        return 2 ** (
            STASButton.cSTAS_DLeft.value if stas else Button.cPadIdx_Left.value
        )

    elif button == "dp-u":
        return 2 ** (STASButton.cSTAS_DUp.value if stas else Button.cPadIdx_Up.value)

    elif button == "dp-r":
        return 2 ** (
            STASButton.cSTAS_DRight.value if stas else Button.cPadIdx_Right.value
        )

    elif button == "dp-d":
        return 2 ** (
            STASButton.cSTAS_DDown.value if stas else Button.cPadIdx_Down.value
        )

    elif button == "ls":
        return 2 ** (
            STASButton.cSTAS_LeftStick.value if stas else Button.cPadIdx_1.value
        )

    elif button == "rs":
        return 2 ** (
            STASButton.cSTAS_RightStick.value if stas else Button.cPadIdx_2.value
        )
    else:
        return 0  # no button found


def nxTAS_Buttons(
    buttons: int, stas: bool
):  # converts button int into string list of buttons for nx-TAS format
    button_list = []
    if buttons == 0:
        return "NONE"
    if buttons & 2 ** (STASButton.cSTAS_A.value if stas else Button.cPadIdx_A.value):
        button_list.append("KEY_A")

    if buttons & 2 ** (STASButton.cSTAS_B.value if stas else Button.cPadIdx_B.value):
        button_list.append("KEY_B")

    if buttons & 2 ** (STASButton.cSTAS_X.value if stas else Button.cPadIdx_X.value):
        button_list.append("KEY_X")

    if buttons & 2 ** (STASButton.cSTAS_Y.value if stas else Button.cPadIdx_Y.value):
        button_list.append("KEY_Y")

    if buttons & 2 ** (STASButton.cSTAS_L.value if stas else Button.cPadIdx_L.value):
        button_list.append("KEY_L")

    if buttons & 2 ** (STASButton.cSTAS_R.value if stas else Button.cPadIdx_R.value):
        button_list.append("KEY_R")

    if buttons & 2 ** (STASButton.cSTAS_ZL.value if stas else Button.cPadIdx_ZL.value):
        button_list.append("KEY_ZL")

    if buttons & 2 ** (STASButton.cSTAS_ZR.value if stas else Button.cPadIdx_ZR.value):
        button_list.append("KEY_ZR")

    if buttons & 2 ** (
        STASButton.cSTAS_Plus.value if stas else Button.cPadIdx_Plus.value
    ):
        button_list.append("KEY_PLUS")

    if buttons & 2 ** (
        STASButton.cSTAS_Minus.value if stas else Button.cPadIdx_Minus.value
    ):
        button_list.append("KEY_MINUS")

    if buttons & 2 ** (
        STASButton.cSTAS_DLeft.value if stas else Button.cPadIdx_Left.value
    ):
        button_list.append("KEY_DLEFT")

    if buttons & 2 ** (
        STASButton.cSTAS_DRight.value if stas else Button.cPadIdx_Right.value
    ):
        button_list.append("KEY_DRIGHT")

    if buttons & 2 ** (STASButton.cSTAS_DUp.value if stas else Button.cPadIdx_Up.value):
        button_list.append("KEY_DUP")

    if buttons & 2 ** (
        STASButton.cSTAS_DDown.value if stas else Button.cPadIdx_Down.value
    ):
        button_list.append("KEY_DDOWN")

    if buttons & 2 ** (
        STASButton.cSTAS_LeftStick.value if stas else Button.cPadIdx_1.value
    ):
        button_list.append("KEY_LSTICK")

    if buttons & 2 ** (
        STASButton.cSTAS_RightStick.value if stas else Button.cPadIdx_2.value
    ):
        button_list.append("KEY_RSTICK")

    return ";".join(button_list)


def prepareToken(token, first_column, row_duration):
    if token[:2] == "//" or token[:2] == '"//':  # ignore comment
        return ""
    return evaluateMath(evaluateVariables(token, row_duration), first_column)


def evaluateVariables(token, row_duration):  # evaluates all variables of form $ or #
    while match_obj := re.search(
        "\\$\\w+", token
    ):  # replace variables with their values
        try:
            token = token.replace(
                match_obj.group(), vars.get(match_obj.group().lower()[1:])
            )
        except:
            sys.exit("Error: Variable " + match_obj.group() + " not found")

    token = token.replace("#", str(row_duration))

    return token.lower()


def evaluateMath(token, whole_token):  # evaluates math expressions
    while match_obj := re.search(
        "\\/[ \\(]*\\.?[0-9]", token
    ):  # replace division / with ÷ to differentiate from loops
        token = token.replace(match_obj.group(), match_obj.group().replace("/", "÷"))
    if whole_token:  # match math expressions that take up the whole token
        math_regex = "^(([0-9,\\. \\+\\-\\*÷\\(\\)])+([\\+\\-\\*÷])([0-9,\\. \\+\\-\\*÷\\(\\)])+)$"
        group = 1
    else:  # match math expressions that begin/end with parentheses, commas, brackets, or semicolons
        math_regex = "([\\(\\,\\;\\[])(([0-9,\\. \\+\\-\\*÷\\(\\)])+([\\+\\-\\*÷])([0-9,\\. \\+\\-\\*÷\\(\\)])+)([\\)\\,\\;\\]])"
        group = 2
    try:
        # evaluate math operations
        while match_obj := re.search(math_regex, token):
            # replace the math expression with its evaluation, first replacing ÷ with / so Python can evaluate the division
            token = token.replace(
                match_obj.group(group),
                str(eval(match_obj.group(group).replace("÷", "/"))),
            )
    except:
        pass  # handles bad match groups with parentheses

    return token.lower()


def evaluateLast(
    token, prev
):  # replaces any ! marks with prev, then calls evaluateMath
    token = token.replace("!", str(prev))
    return evaluateMath(token, True)


def evaluateCurrentFrame(
    token, offset
):  # replaces any @ marks with offset, then calls evaluateMath
    token = token.replace("@", str(offset))
    return evaluateMath(token, True)


# parses the duration of a token
def parseDuration(token, default):
    try:
        duration_str = token[token.index("[") + 1 : token.index("]")].strip()
        if duration_str == "?" or duration_str == "*":  # special duration characters
            duration = duration_str
        else:
            try:
                duration = int(float(duration_str))  # rounds down floats
            except:
                sys.exit("Error: Invalid local duration in row " + lineInNumber)
        token = token.replace(token[token.index("[") : token.index("]") + 1], "")
        return token.strip(), duration
    except:
        return token, default


# prev_frame is used to evaluate ! characters if it is not None
# offset_from_row_index is used to evaluate @ characters if it is not None
def getStickPolar(token, right_stick, prev_frame, offset_from_row_index):
    r = 1.0
    theta = 0.0
    if prev_frame is not None:  # contains !
        if right_stick:
            prev_stick = prev_frame.right_stick
        else:
            prev_stick = prev_frame.left_stick
    if ";" in token:  # (r; theta)
        r_token = token[0 : token.index(";")]
        theta_token = token[token.index(";") + 1 :]
        if prev_frame is not None:
            r_token, theta_token = evaluateLast(r_token, prev_stick.r), evaluateLast(
                theta_token, prev_stick.theta - ls_offset
            )
        if offset_from_row_index is not None:
            r_token, theta_token = evaluateCurrentFrame(
                r_token, offset_from_row_index
            ), evaluateCurrentFrame(theta_token, offset_from_row_index)
        r, theta = float(r_token), float(theta_token)
    else:  # (r)
        if prev_frame is not None:
            token = evaluateLast(token, prev_stick.theta - ls_offset)
        if offset_from_row_index is not None:
            token = evaluateCurrentFrame(token, offset_from_row_index)
        theta = float(token)
    theta += ls_offset
    return r, theta


# euler in degrees to rotation matrix
def toRotationMatrix(euler: Vector3f):
    euler_radians = Vector3f.zero()
    euler_radians.x, euler_radians.y, euler_radians.z = (
        math.radians(euler.x),
        math.radians(euler.y),
        math.radians(euler.z),
    )

    cx = math.cos(euler_radians.x)
    cy = math.cos(euler_radians.y)
    cz = math.cos(euler_radians.z)
    sx = math.sin(euler_radians.x)
    sy = math.sin(euler_radians.y)
    sz = math.sin(euler_radians.z)

    return Matrix33f(
        to_f2(cy * cz),
        to_f2(-cy * sz),
        to_f2(sy),
        to_f2(cz * sx * sy + cx * sz),
        to_f2(cx * cz - sx * sy * sz),
        to_f2(-cy * sx),
        to_f2(-cx * cz * sy + sx * sz),
        to_f2(cz * sx + cx * sy * sz),
        to_f2(cx * cy),
    )


def getGyroValues(token):
    all = token.split(
        ";"
    )  # (pitch; yaw; roll) or #(pitch; yaw; roll; ang-x; ang-y; ang-z)
    ang_vel = Vector3f.zero()
    euler = Vector3f.zero()
    if len(all) == 6:
        ang_vel.x, ang_vel.y, ang_vel.z = (
            to_f2(float(all[3])),
            to_f2(float(all[4])),
            to_f2(float(all[5])),
        )
    euler.x, euler.y, euler.z = float(all[0]), float(all[1]), float(all[2])

    return Gyro(euler, toRotationMatrix(euler), ang_vel)


# calculates needed angular velocities for all frames based on the gyroscope
def calculateAngularVelocity(player_two):
    euler_left_old, euler_right_old = (
        script.getFrames(player_two)[0].gyro_left.euler,
        script.getFrames(player_two)[0].gyro_right.euler,
    )
    for i in range(1, len(script.getFrames(player_two))):
        euler_left, euler_right = (
            script.getFrames(player_two)[i].gyro_left.euler,
            script.getFrames(player_two)[i].gyro_right.euler,
        )
        if not script.getFrames(player_two)[i].macro:
            script.getFrames(player_two)[i].gyro_left.ang_vel = Vector3f(
                ANG_VEL_FACTOR * (euler_left.x - euler_left_old.x),
                ANG_VEL_FACTOR * (euler_left.y - euler_left_old.y),
                ANG_VEL_FACTOR * (euler_left.z - euler_left_old.z),
            )
            script.getFrames(player_two)[i].gyro_right.ang_vel = Vector3f(
                ANG_VEL_FACTOR * (euler_right.x - euler_right_old.x),
                ANG_VEL_FACTOR * (euler_right.y - euler_right_old.y),
                ANG_VEL_FACTOR * (euler_right.z - euler_right_old.z),
            )
        """
        else:
            ang_vel_left, ang_vel_right = script.frames[i].gyro_left.ang_vel, script.frames[i].gyro_right.ang_vel
            script.frames[i].gyro_left.euler = Vector3f(euler_left_old.x + ang_vel_left.x / ANG_VEL_FACTOR, euler_left_old.y + ang_vel_left.y / ANG_VEL_FACTOR, euler_left_old.z + ang_vel_left.z / ANG_VEL_FACTOR)
            script.frames[i].gyro_right.euler = Vector3f(euler_right_old.x + ang_vel_right.x / ANG_VEL_FACTOR, euler_right_old.y + ang_vel_right.y / ANG_VEL_FACTOR, euler_right_old.z + ang_vel_right.z / ANG_VEL_FACTOR)
            script.frames[i].gyro_left.direction = toRotationMatrix(script.frames[i].gyro_left.euler)
            script.frames[i].gyro_right.direction = toRotationMatrix(script.frames[i].gyro_right.euler)
        """
        euler_left_old, euler_right_old = euler_left, euler_right


# parses token into subtokens
def parseToken(token, indexWrite, duration, rowIndex, rowDuration):
    if debug:
        print("Parsing Token: " + token)
        print("Write Index: " + str(indexWrite))

    token = token.strip()
    if re.search("^\\[[0-9]*\\] *\\(", token) or (
        not "|" in token and not "/" in token
    ):
        token, duration = parseDuration(
            token, duration
        )  # see if there is a duration associated with the token

    if debug:
        print("Duration: " + str(duration))

    if len(token) > 0 and token[0] == "(" and token[-1] == ")":
        token = token[1:-1]  # remove enclosing parentheses

    if "|" in token:
        parseSequence(token, indexWrite, rowIndex, rowDuration)
    elif "/" in token:
        parseLoop(token, indexWrite, duration, rowIndex, rowDuration)
    elif "&" in token:
        for subtoken in token.split("&"):
            parseToken(subtoken, indexWrite, duration, rowIndex, rowDuration)
    elif "->" in token:
        parseInterpolatedStick(token, indexWrite, duration)
    else:
        if duration == "?":
            sys.exit("Error: ? duration only allowed within sequences")
        elif duration == "*":
            addToggle(token, indexWrite, True)
        elif duration == 0:
            addToggle(token, indexWrite, False)
        elif duration > 0:
            addToFrameRange(token, range(indexWrite, indexWrite + duration), rowIndex)
        else:
            addToFrameRange(
                token, range(indexWrite - 1, indexWrite + duration - 1, -1), rowIndex
            )


def parseInterpolatedStick(token, indexStart, duration):
    if "@" in token:
        sys.exit(
            "Error: Stick interpolation on line "
            + str(lineInNumber)
            + " cannot use @ symbol"
        )
    if duration < 0:
        sys.exit(
            "Error: Stick interpolation on line "
            + str(lineInNumber)
            + " cannot have negative duration"
        )
    if duration < 2:
        sys.exit(
            "Error: Stick interpolation on line "
            + str(lineInNumber)
            + " must have duration of at least 2"
        )

    player_two = "c" in token

    # add frames as necessary
    script.addFrames(indexStart + duration)
    indexStop = indexStart + duration

    if indexStart - 1 < 0:
        prev_frame = blankFrame
    else:
        prev_frame = script.getFrames(player_two)[indexStart - 1]

    try:
        token1, token2 = token.split("->")

        right = False  # True if right stick/gyro/etc., False if left
        if "r" in token1:
            right = True

        token1 = token1[token1.index("(") + 1 : token1.index(")")]
        token2 = token2[token2.index("(") + 1 : token2.index(")")]

        r1, theta1 = getStickPolar(token1, right, prev_frame, None)
        r2, theta2 = getStickPolar(token2, right, prev_frame, None)

        dr = (r2 - r1) / (duration - 1)
        dtheta = (theta2 - theta1) / (duration - 1)

        r, theta = r1, theta1

        for i in range(indexStart, indexStop):
            if right:
                script.getFrames(player_two)[i].right_stick = Joystick.polar((r, theta))
            else:
                script.getFrames(player_two)[i].left_stick = Joystick.polar((r, theta))
            r += dr
            theta += dtheta
        if right:
            script.getFrames(player_two)[indexStop - 1].right_stick = Joystick.polar(
                (r2, theta2)
            )
        else:
            script.getFrames(player_two)[indexStop - 1].left_stick = Joystick.polar(
                (r2, theta2)
            )
    except Exception as e:
        if debug:
            print(e)
        sys.exit(
            "Error: Syntax error(s) on line "
            + str(lineInNumber)
            + " prevented script generation"
        )


def parseSequence(token, indexWrite, rowIndex, rowDuration):
    steps = token.split("|")
    for i in range(len(steps)):
        subtoken, duration = parseDuration(steps[i], 1)  # parse out duration
        if duration == "*":
            sys.exit(
                "Error: * not supported for durations within sequences (line "
                + str(lineInNumber)
                + ")"
            )
        elif duration == "?":
            duration = rowDuration + rowIndex - indexWrite
            if duration < 0:
                duration = 0
        parseToken(subtoken, indexWrite, duration, rowIndex, rowDuration)
        indexWrite += duration


def parseLoop(token, indexWrite, duration, rowIndex, rowDuration):
    if duration == "*" or duration == "?":
        sys.exit(
            duration
            + " not supported for durations within sequences (line "
            + str(lineInNumber)
            + ")"
        )
    elif duration == 0:
        return
    elif duration < 0:
        sys.exit(
            "Error: Loop on line "
            + str(lineInNumber)
            + " cannot have negative total duration"
        )

    remainingDuration = duration
    steps = token.split("/")
    subtokens = []
    durations = []
    for i in range(len(steps)):
        subtoken, duration = parseDuration(steps[i], 1)  # parse out duration
        subtokens.append(subtoken)
        durations.append(duration)
    while remainingDuration > 0:
        for i in range(len(steps)):
            if remainingDuration <= 0:
                return
            if durations[i] >= 0:
                parseToken(
                    subtokens[i],
                    indexWrite,
                    min(durations[i], remainingDuration),
                    rowIndex,
                    rowDuration,
                )
                remainingDuration -= durations[i]
            else:
                sys.exit("Error: Negative durations are not permitted within loops")
            indexWrite += durations[i]


def addToFrameRange(token, frameRange: range, rowIndex):
    # first find start and end frames involved, add any additional frames as needed
    minFrame = maxFrame = 0
    for j in frameRange:
        if j > maxFrame:
            maxFrame = j
        if j < minFrame:
            minFrame = j
    script.addFrames(maxFrame + 1)

    if frameRange.start < 0 or frameRange.stop < -1:
        sys.exit("Error: Negative durations cannot go before frame 0")

    player_two = False
    token = token.strip()
    if len(token) > 0 and token[0] == "c":
        player_two = True
        token = token[1:]  # get rid of the c

    try:
        if "(" in token:  # stick/motion
            right = True  # True if right stick/gyro/etc.
            left = True  # True if left stick/gyro/etc.
            if "r" in token:
                left = False
            if "l" in token:
                right = False
            prefix = token[0 : token.index("(")]
            token = token[token.index("(") + 1 : token.rfind(")")]

            if "s" in prefix:  # stick
                previous_input_symbol = "!" in token
                current_symbol = "@" in token
                if "x" in prefix:
                    coords = Joystick.cartesian(
                        int(token.split(";")[0]), int(token.split(";")[1])
                    )
                    for j in frameRange:
                        if right:
                            script.getFrames(player_two)[j].right_stick = coords
                        if left:
                            script.getFrames(player_two)[j].left_stick = coords
                elif (
                    previous_input_symbol or current_symbol
                ):  # need to calculate each frame individually
                    for j in frameRange:
                        if previous_input_symbol:
                            if j - 1 < 0:
                                prev_frame = blankFrame
                            else:
                                prev_frame = script.getFrames(player_two)[j - 1]
                        else:
                            prev_frame = None
                        coords = Joystick.polar(
                            getStickPolar(token, right, prev_frame, j - rowIndex)
                        )
                        if right:
                            script.getFrames(player_two)[j].right_stick = coords
                        if left:
                            script.getFrames(player_two)[j].left_stick = coords
                else:
                    polar_coords = getStickPolar(token, right, None, None)
                    coords = Joystick.polar(polar_coords)
                    for j in frameRange:
                        if right:
                            script.getFrames(player_two)[j].right_stick = coords
                        if left:
                            script.getFrames(player_two)[j].left_stick = coords

            elif "a" in prefix:  # accelerometer
                accel = Vector3f(*map(to_f2, map(float, token.split(";"))))

                for j in frameRange:
                    if right:
                        script.getFrames(player_two)[j].accel_right = accel
                    if left:
                        script.getFrames(player_two)[j].accel_left = accel

            elif "g" in prefix:  # gyroscope
                gyro = getGyroValues(token)

                for j in frameRange:
                    if right:
                        script.getFrames(player_two)[j].gyro_right = gyro
                    if left:
                        script.getFrames(player_two)[j].gyro_left = gyro

        elif token == "m" or "m-" in token:  # motion macros
            if motion_offset != 0:  # shifting motion earlier or later
                newStart = frameRange.start + motion_offset
                while newStart < 0:
                    newStart += frameRange.step
                newStop = max(frameRange.stop + motion_offset, -1)
                frameRange = range(newStart, newStop, frameRange.step)

            if (
                motion_offset > 0
            ):  # ensure there are still enough frames if motion is shifted later
                minFrame = maxFrame = 0
                for j in frameRange:
                    if j > maxFrame:
                        maxFrame = j
                    if j < minFrame:
                        minFrame = j
                script.addFrames(maxFrame + 1)

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
                    (
                        script.getFrames(player_two)[j].accel_left,
                        script.getFrames(player_two)[j].accel_right,
                    ) = (accel_left, accel_right)
                    (
                        script.getFrames(player_two)[j].gyro_left,
                        script.getFrames(player_two)[j].gyro_right,
                    ) = (gyro_left, gyro_right)
                    script.getFrames(player_two)[j].macro = True

            else:  # nx-tas motion keybinds
                l_button = False
                if token == "m":
                    l_button = True
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
                elif token == "m-uu":
                    token = "dp-u"
                elif token == "m-dd":
                    token = "dp-d"
                elif token == "m-ll":
                    token = "dp-l"
                elif token == "m-rr":
                    token = "dp-r"
                else:
                    return

                if l_button:
                    for j in frameRange:
                        script.getFrames(player_two)[j].buttons |= (
                            2**Button.cPadIdx_L.value
                            if not stas
                            else 2**STASButton.cSTAS_L.value
                        )

                # include dpad button

                button_bin = getButtonBin(token, stas)
                for j in frameRange:
                    script.getFrames(player_two)[j].buttons |= button_bin

        else:  # button or comment/invalid
            button_bin = getButtonBin(token, stas)
            for j in frameRange:
                script.getFrames(player_two)[j].buttons |= button_bin

    except Exception as e:
        if debug:
            print(e)
        sys.exit(
            "Syntax error(s) on line "
            + str(lineInNumber)
            + " prevented script generation"
        )


# add a toggle for a button to be on indefinitely until its next input in the script ([*]) or a toggle to switch such a button off ([0]) – but the program will actually fill in the frames later
def addToggle(token, indexWrite, on):
    try:
        player_two = "c" in token
        button_bin = getButtonBin(token, stas)

        script.addFrames(indexWrite + 1)
        if on:
            script.getFrames(player_two)[indexWrite].buttonsOn |= button_bin
        else:
            script.getFrames(player_two)[indexWrite].buttonsOff |= button_bin
    except Exception as e:
        if debug:
            print(e)
        sys.exit(
            "Syntax error(s) on line "
            + str(lineInNumber)
            + " prevented script generation"
        )(
            "Syntax error(s) on line "
            + str(lineInNumber)
            + " prevented script generation"
        )


def eulerToQuat(euler_deg: Vector3f) -> Quat4f:
    quat = Quat4f.unit()
    euler.x = math.radians(euler_deg.x)
    euler.y = math.radians(euler_deg.y)
    euler.z = math.radians(euler_deg.z)
    cy = math.cos(euler.y / 2)
    sy = math.sin(euler.y / 2)
    cp = math.cos(euler.z / 2)
    sp = math.sin(euler.z / 2)
    cr = math.cos(euler.x / 2)
    sr = math.sin(euler.x / 2)

    quat.w = cr * cp * cy + sr * sp * sy
    quat.x = sr * cp * cy - cr * sp * sy
    quat.z = cr * sp * cy + sr * cp * sy
    quat.y = cr * cp * sy - sr * sp * cy

    return quat


def writeCommand(file: FileIO, type: int, size: int, data: bytes) -> None:
    file.write(struct.pack("<H", type))
    file.write(size.to_bytes(6, "little"))
    file.write(data)


def writeCmdFrame(file: FileIO, frame: int) -> None:
    data: bytes = frame.to_bytes(4, "little")
    # print(f"CmdFrame: {frame}")

    writeCommand(file, 0, 4, data)


def writeCmdController(
    file: FileIO, player: int, buttons: bytes, left: Joystick, right: Joystick
) -> None:
    data: bytes = player.to_bytes(1, "little")
    data += buttons
    data += left.x.to_bytes(4, "little", signed=True)
    data += left.y.to_bytes(4, "little", signed=True)
    data += right.x.to_bytes(4, "little", signed=True)
    data += right.y.to_bytes(4, "little", signed=True)
    # print(f"CmdController: {player}, {bin(int.from_bytes(buttons,"little"))}, {left.x}, {left.y}, {right.x}, {right.y}")

    writeCommand(file, 1, 0x18, data)


def writeCmdMotion(
    file: FileIO, player: int, controllerID: int, accel: Vector3f, gyro: Vector3f
) -> None:
    data: bytes = player.to_bytes(1, "little")
    data += controllerID.to_bytes(1, "little")
    data += struct.pack("<2x")
    data += struct.pack("<3f", accel.x, accel.y, accel.z)
    data += struct.pack("<3f", gyro.x, gyro.y, gyro.z)
    # print(f"CmdMotion: {player}, {controllerID}, {accel.x}, {accel.y}, {accel.z}, {gyro.x}, {gyro.y}, {gyro.z}")

    writeCommand(file, 2, 0x1C, data)


def writeCmdSaveFile(file:FileIO,id:int,reload:bool) -> None:
    data:bytes = struct.pack("<b?",id,reload)
    writeCommand(file,0xC000,0x2,data)

def writeCmdGo(
    file: FileIO,
    scenario: int,
    subScenario: int,
    returnPrev: bool,
    stageName: str,
    entr: str,
) -> None:
    data: bytes = struct.pack("<BB?x", scenario, subScenario, returnPrev)
    data += (len(stageName) + 1).to_bytes(2, "little")
    data += bytes(stageName, "utf-8") + b"\x00"
    data += (len(entr) + 1).to_bytes(2, "little")
    data += bytes(entr, "utf-8") + b"\x00"

    writeCommand(file, 0xC001, 8 + len(stageName) + 1 + len(entr) + 1, data)


def writeCmdTp(file: FileIO, pos: Vector3f, rot: Quat4f, isCap: bool) -> None:
    data: bytes = struct.pack("<3f", pos.x, pos.y, pos.z)
    data += struct.pack("<4f", rot.x, rot.y, rot.z, rot.w)
    writeCommand(file, 0xC003 if isCap else 0xC002, 0xC + 0x10, data)


def writeCmdAbsStick(file: FileIO, enable: bool) -> None:
    data: bytes = struct.pack("<?", enable)
    data += struct.pack("<3x")
    writeCommand(file, 0xC004, 0x4, data)


def writeCmdSpeedup(file: FileIO, speed: int) -> None:
    data: bytes = struct.pack("<b", speed)
    data += struct.pack("<3x")
    writeCommand(file, 0xC005, 0x4, data)

def writeCmdDemo(file:FileIO, enable: bool) -> None: 
    data:bytes = struct.pack("<?",enable)
    data += struct.pack("<3x")
    writeCommand(file,0xc007,0x4,data)

def align_up(value, alignment):
    return ((value + alignment - 1) // alignment) * alignment


do_once = True

if loop:
    print("Press enter to run command")
    print('Type "q" and press enter to quit')

while loop or do_once:
    do_once = False

    if loop:
        input_text = input()
        if input_text == "q" or input_text == "quit" or input_text == "exit":
            break

    blankFrame = Frame(
        0,
        False,
        0,
        0,
        0,
        Joystick.zero(),
        Joystick.zero(),
        Vector3f.default_accel(),
        Vector3f.default_accel(),
        Gyro.zero(),
        Gyro.zero(),
        False,
    )

    script = Script("", "", 1, False, Vector3f.zero())

    motion_offset = 0
    ls_offset = 0
    independent_gyro = False

    num_frames = 0

    lineInNumber = 1

    # count frames roughly to initialize array
    with open(infile) as f:
        for lineIn in f:
            duration = 1
            first = lineIn.split(separator)[0]
            try:
                duration = int(first)
            except:
                if first == "":
                    pass
                else:
                    continue
            num_frames += duration
        f.close()

    script.frames_P1 = [
        Frame(
            i,
            False,
            0,
            0,
            0,
            Joystick.zero(),
            Joystick.zero(),
            Vector3f.default_accel(),
            Vector3f.default_accel(),
            Gyro.zero(),
            Gyro.zero(),
            False,
        )
        for i in range(num_frames)
    ]
    if script.is_two_player:
        script.frames_P2 = [
            Frame(
                i,
                True,
                0,
                0,
                0,
                Joystick.zero(),
                Joystick.zero(),
                Vector3f.default_accel(),
                Vector3f.default_accel(),
                Gyro.zero(),
                Gyro.zero(),
                False,
            )
            for i in range(num_frames)
        ]

    indexStart = 0
    indexStop = 0

    vars = dict()

    with open(infile) as f:
        prevLineInDuration = 1
        for lineIn in f:
            if debug:
                print(lineIn)
            lineIn = lineIn.split("\t")  # type: ignore
            lineIn[-1] = lineIn[-1].strip()  # type: ignore

            # handle first token (duration or variable assignment)
            lineInDuration = 1
            first = lineIn[0].strip()
            try:
                lineInDuration = int(float(first))
            except:
                if first == "*":  # toggle on the buttons
                    lineInDuration = "*"  # type: ignore
                elif first == "?":
                    sys.exit("Error: ? duration only allowed within sequences")
                elif first == "":
                    pass
                elif first[0] == "$":  # variables
                    if "=" in first:  # variable assignment
                        var = first[1 : first.index("=")].strip().lower()
                        value = first[first.index("=") + 1 :].strip()

                        # script start variables
                        if var == "stage":
                            script.change_stage_name = value
                        elif var == "entr" or var == "entrance":
                            script.change_stage_id = value
                        elif var == "scen" or var == "scenario":
                            try:
                                script.scenario_no = int(value)
                            except:
                                sys.exit("Error: Invalid scenario number")
                        elif var == "independent_gyro" or var == "ind_gyro":
                            if value.lower() == "true" or value.lower() == "t":
                                independent_gyro = True
                        elif var == "pos" or var == "position":
                            value = value[value.index("(") + 1 : value.index(")")]
                            coords = value.split(";")
                            script.startPosition.x = float(coords[0])
                            script.startPosition.y = float(coords[1])
                            script.startPosition.z = float(coords[2])
                        elif var == "motion_offset":
                            motion_offset = int(value)
                        elif var == "ls_offset":
                            ls_offset = float(value)
                        elif var == "is2p" or var == "is_two_player":
                            if value.lower() == "true" or value.lower() == "t":
                                script.is_two_player = True
                                is_two_player = True

                        # add variable values to dictionary
                        value = prepareToken(value, True, 0)
                        vars.update({var: value})
                        lineInNumber += 1
                        continue
                    else:
                        try:
                            lineInDuration = int(
                                float(
                                    evaluateLast(
                                        prepareToken(first, True, 0), prevLineInDuration
                                    )
                                )
                            )
                        except:
                            lineInNumber += 1
                            continue
                elif first[0] == "/" and first[1] != "/":  # commands
                    for _ in range(len(script.commands), indexStart + 1):
                        script.commands.append([])
                    script.commands[indexStart].append(first[1:])
                    lineInNumber += 1
                    continue
                else:
                    try:
                        lineInDuration = int(
                            float(
                                evaluateLast(
                                    prepareToken(first, True, 0), prevLineInDuration
                                )
                            )
                        )
                    except:
                        lineInNumber += 1
                        continue

            for i in range(1, len(lineIn)):
                if lineIn[i] == "":
                    continue

                # perform all variable evaluation and as much math evaluation as possible
                token = prepareToken(lineIn[i], False, lineInDuration)

                if debug:
                    print("Line Duration: " + str(lineInDuration))
                parseToken(
                    token, indexStart, lineInDuration, indexStart, lineInDuration
                )

            if lineInDuration == "*":
                lineInDuration = 0
            indexStart += lineInDuration
            lineInNumber += 1
            prevLineInDuration = lineInDuration

        # add empty frames to end of script as needed to reach the total number of frames
        if not remove_empty:
            script.addFrames(indexStart)

        # now that all the inputs have been parsed, go through again to process toggled buttons
        buttonsOn = 0
        for frame in script.frames_P1:
            buttonsOn |= frame.buttonsOn
            buttonsOff = frame.buttons | frame.buttonsOff
            buttonsOn &= ~buttonsOff
            frame.buttons |= buttonsOn
        if script.is_two_player:
            for frame in script.frames_P2:
                buttonsOn |= frame.buttonsOn
                buttonsOff = frame.buttons | frame.buttonsOff
                buttonsOn &= ~buttonsOff
                frame.buttons |= buttonsOn

        # blankFrame = Frame(0, False, 0, Joystick.zero(), Joystick.zero(), Vector3f.default_accel(), Vector3f.default_accel(), Gyro.zero(), Gyro.zero(), False)

        # calculate angular velocity if gyroscope and angular velocity are not independent, or calculate proper gyroscope if a motion macro is used
        # angular velocity is change in gyroscope in degrees times -3/400
        if not independent_gyro:
            calculateAngularVelocity(False)
            if script.is_two_player:
                calculateAngularVelocity(True)

        # remove empty frames (in 2P, only remove if both are empty)
        if remove_empty:
            if script.is_two_player:
                modelFrame_1P = modelFrame_2P = blankFrame
                for i in range(len(script.frames_P1) - 1, -1, -1):
                    modelFrame_1P.step = modelFrame_2P.step = i
                    modelFrame_1P.buttonsOn = script.frames_P1[i].buttonsOn
                    modelFrame_1P.buttonsOff = script.frames_P1[i].buttonsOff
                    modelFrame_2P.buttonsOn = script.frames_P2[i].buttonsOn
                    modelFrame_2P.buttonsOff = script.frames_P2[i].buttonsOff
                    if (
                        modelFrame_1P == script.frames_P1[i]
                        and modelFrame_2P == script.frames_P2[i]
                    ):
                        del script.frames_P1[i]
                        del script.frames_P2[i]
            else:
                modelFrame = blankFrame
                for i in range(len(script.frames_P1) - 1, -1, -1):
                    modelFrame.step = i
                    modelFrame.buttonsOn = script.frames_P1[i].buttonsOn
                    modelFrame.buttonsOff = script.frames_P1[i].buttonsOff
                    if modelFrame == script.frames_P1[i]:
                        del script.frames_P1[i]

    # write all 1P and 2P frames to the same array
    script.combineFrames()

    if debug:
        debugFile = open(outfile + "-debug.csv", "w")

        debugFile.write(
            "Frame,2ndPlayer,Buttons,ButtonsOn,ButtonsOff,lx.r,ls.theta,ls.x,ls.y,rs.r,rs.theta,rs.x,rs.y,la.x,la.y,la.z,ra.x,ra.y,ra.z,lg.r.xx,lg.r.xy,lg.r.xz,lg.r.yx,lg.r.yy,lg.r.yz,lg.r.zx,lg.r.zy,lg.r.zz,lg.v.x,lg.v.y,lg.v.z,rg.r.xx,rg.r.xy,rg.r.xz,rg.r.yx,rg.r.yy,rg.r.yz,rg.r.zx,rg.r.zy,rg.r.zz,rg.v.x,rg.v.y,rg.v.z,Command\n"
        )
        for i in range(len(script.frames)):
            csv_writer = csv.writer(debugFile, delimiter=",")
            data = script.frames[i].toStrArray()
            csv_writer.writerow(data)
        debugFile.close()

    if nxtas:
        outf: FileIO = cast(FileIO, open(outfile, "w"))
        for frame in script.frames:
            outf.write(
                str(frame.step)
                + " "
                + nxTAS_Buttons(frame.buttons, stas)
                + " "
                + str(frame.left_stick.x)
                + ";"
                + str(frame.left_stick.y)
                + " "
                + str(frame.right_stick.x)
                + ";"
                + str(frame.right_stick.y)
                + "\n"
            )

    elif stas:
        size: int = 0
        prevFrame: int = -1
        prevMotion: list[list[list[Vector3f]]] = [  # player, left/right, accel/gyro
            [[Vector3f.zero(), Vector3f.zero()], [Vector3f.zero(), Vector3f.zero()]],
            [[Vector3f.zero(), Vector3f.zero()], [Vector3f.zero(), Vector3f.zero()]],
        ]
        prevController: list[list[object]] = (
            [  # player, button/left joystick/right joystick
                [0, Joystick.zero(), Joystick.zero()],
                [0, Joystick.zero(), Joystick.zero()],
            ]
        )

        outf = cast(FileIO, open(outfile, "wb"))
        # File Header
        size += outf.write(b"STAS")
        size += outf.write(
            struct.pack("<3H2xQ", 0x0001, 0x0000, 0x0000, 0x0100000000010000)
        )  # Format Ver, Game Addon Ver, Editor Ver, Title Id

        # Script Header
        size += outf.write(struct.pack("<I", 0))  # TODO: Command Count
        size += outf.write(
            struct.pack("<I", script.frames[-1].step)
        )  # TODO: This is bad
        size += outf.write(struct.pack("<I", 0))  # Editing time in seconds
        size += outf.write(
            struct.pack("<8B", 2, 2 if script.is_two_player else 0, 0, 0, 0, 0, 0, 0)
        )  # Controller types per player

        author = b"TSV-TAS-2\x00"
        size += outf.write(struct.pack("<H", len(author)))  # Author Length
        size += outf.write(author)  # Author
        align = align_up(size, 4)
        size += outf.write(struct.pack(f"<{align-size}x"))

        # title = b"TSV-TAS-2 Script\x00"
        title = bytes(infile.split("/")[-1], "utf-8")
        title += b"\x00"
        size += outf.write(struct.pack("<I", len(title)))  # Title Length
        size += outf.write(title)
        align = align_up(size, 4)
        size += outf.write(struct.pack(f"<{align-size}x"))

        desc = b"Description from TSV-TAS-2\x00"
        size += outf.write(struct.pack("<I", len(desc)))  # Description Length
        size += outf.write(desc)
        align = align_up(size, 4)
        size += outf.write(struct.pack(f"<{align-size}x"))

        if script.change_stage_name:
            writeCmdGo(
                outf,
                script.scenario_no,
                0,
                False,
                script.change_stage_name,
                script.change_stage_id,
            )

        # reset every controller state
        writeCmdController(
            outf, 0, int(0).to_bytes(7, "little"), Joystick.zero(), Joystick.zero()
        )
        writeCmdController(
            outf, 1, int(0).to_bytes(7, "little"), Joystick.zero(), Joystick.zero()
        )
        writeCmdMotion(outf, 0, 2, Vector3f.zero(), Vector3f.zero())
        writeCmdMotion(outf, 1, 2, Vector3f.zero(), Vector3f.zero())

        for frame in script.frames:
            # print(f"{frame.step}, {prevFrame}")
            if frame.step > prevFrame:  # do only for 1P frames
                prevFrame = frame.step
                writeCmdFrame(outf, frame.step)
                if frame.step == 0 and (
                    script.startPosition.x != 0
                    or script.startPosition.y != 0
                    or script.startPosition.z != 0
                ):
                    writeCmdTp(outf, script.startPosition, Quat4f.unit(), False)
                # parse commands, this relies on every step being included but that is okay
                for command_str in script.commands[frame.step]:
                    tokens = command_str.split(" ")
                    command = tokens[0]
                    if debug:
                        print("Parsing command: " + str(command))
                    if command == "tp" or command == "ctp":
                        isCap = command == "ctp"
                        euler = Vector3f.zero()
                        quat = Quat4f.unit()
                        if len(tokens) in (4, 5, 7, 8):
                            try:
                                x, y, z = map(float, tokens[1:4])
                                if len(tokens) == 5 or len(tokens) == 7:
                                    if len(tokens) == 5:
                                        euler.y = float(tokens[4])
                                    elif len(tokens) == 7:
                                        euler.x, euler.y, euler.z = map(
                                            float, tokens[4:7]
                                        )
                                    quat = eulerToQuat(euler)
                                elif len(tokens) == 8:
                                    quat.x, quat.y, quat.z, quat.w = map(
                                        float, tokens[4:8]
                                    )
                                writeCmdTp(outf, Vector3f(x, y, z), quat, isCap)
                                if debug:
                                    print("Quat: " + str(quat))
                            except:
                                sys.exit(
                                    f"Error: /{command} coordinates must be numbers"
                                )
                        else:
                            sys.exit(f"Error: incorrect number of args for /{command}")
                    elif command == "absStick":
                        if len(tokens) == 2:
                            enable: bool = tokens[1] in ["true", "1", "on", "y", "yes"]
                            writeCmdAbsStick(outf, enable)
                        else:
                            sys.exit(f"Error: incorrect number of args for /{command}")
                    elif command == "speed":
                        if len(tokens) == 2:
                            speed: int = int(tokens[1])
                            if speed > 10 or speed < 1:
                                sys.exit(
                                    f"Error: speed has to be between 1 and 10 inclusive"
                                )
                            writeCmdSpeedup(outf, speed)
                        else:
                            sys.exit(f"Error: incorrect number of args for /{command}")
                    elif command == "pause":
                        if len(tokens) == 1:
                            writeCommand(outf, 0xC006, 0, b"")
                        else:
                            sys.exit(f"Error: incorrect number of args for /{command}")
                    elif command == "loadFile": 
                        if len(tokens) == 2:
                            writeCmdSaveFile(outf,int(tokens[1]),False)
                        else:
                            sys.exit(f"Error: incorrect number of args for /{command}")
                    elif command == "reloadFile": 
                        if len(tokens) == 1:
                            writeCmdSaveFile(outf,0,True)
                        else:
                            sys.exit(f"Error: incorrect number of args for /{command}")
                    elif command == "demo":
                        if len(tokens) == 2:
                            enable: bool = tokens[1] in ["true", "1", "on", "y", "yes"]
                            writeCmdDemo(outf, enable)
                        else:
                            sys.exit(f"Error: incorrect number of args for /{command}")
            # only write controller inputs if they differ
            if (prevController[frame.second_player][0] != frame.buttons) or (
                prevController[frame.second_player][1] != frame.left_stick
                or prevController[frame.second_player][2] != frame.right_stick
            ):
                writeCmdController(
                    outf,
                    frame.second_player,
                    frame.buttons.to_bytes(7, "little"),
                    frame.left_stick,
                    frame.right_stick,
                )
                if debug:
                    print(
                        "Wrote frame "
                        + str(frame.step)
                        + ", P2: "
                        + str(frame.second_player)
                    )

            prevController[frame.second_player] = [
                frame.buttons,
                frame.left_stick,
                frame.right_stick,
            ]

            if (vec3fNEQ0(frame.accel_left) or vec3fNEQ0(frame.gyro_left.ang_vel)) or (
                vec3fNEQ0(prevMotion[frame.second_player][0][0])
                or vec3fNEQ0(prevMotion[frame.second_player][0][1])
            ):
                writeCmdMotion(
                    outf,
                    frame.second_player,
                    0,
                    frame.accel_left,
                    frame.gyro_left.ang_vel,
                )
                prevMotion[frame.second_player][0] = [
                    frame.accel_left,
                    frame.gyro_left.ang_vel,
                ]

            if (
                vec3fNEQ0(frame.accel_right)
                or vec3fNEQ0(frame.gyro_right.ang_vel)
                or (
                    vec3fNEQ0(prevMotion[frame.second_player][1][0])
                    or vec3fNEQ0(prevMotion[frame.second_player][1][1])
                )
            ):
                writeCmdMotion(
                    outf,
                    frame.second_player,
                    1,
                    frame.accel_right,
                    frame.gyro_right.ang_vel,
                )
                prevMotion[frame.second_player][1] = [
                    frame.accel_right,
                    frame.gyro_right.ang_vel,
                ]

    else:
        outf = cast(FileIO, open(outfile, "wb"))
        outf.write(b"BOOB")
        outf.write(
            struct.pack(
                "<I?3xi", len(script.frames), script.is_two_player, script.scenario_no
            )
        )
        outf.write(
            bytes(script.change_stage_name, encoding="ascii")
            + b"\0" * (128 - len(script.change_stage_name))
        )
        outf.write(
            bytes(script.change_stage_id, encoding="ascii")
            + b"\0" * (128 - len(script.change_stage_id))
        )
        outf.write(
            struct.pack(
                "<3f",
                script.startPosition.x,
                script.startPosition.y,
                script.startPosition.z,
            )
        )

        for frame in script.frames:
            outf.write(
                struct.pack("<I?3xI", frame.step, frame.second_player, frame.buttons)
            )
            outf.write(
                struct.pack(
                    "<2f", frame.left_stick.x / 32767.0, frame.left_stick.y / 32767.0
                )
            )
            outf.write(
                struct.pack(
                    "<2f", frame.right_stick.x / 32767.0, frame.right_stick.y / 32767.0
                )
            )
            outf.write(
                struct.pack(
                    "<3f", frame.accel_left.x, frame.accel_left.y, frame.accel_left.z
                )
            )
            outf.write(
                struct.pack(
                    "<3f", frame.accel_right.x, frame.accel_right.y, frame.accel_right.z
                )
            )
            outf.write(
                struct.pack(
                    "<9f",
                    frame.gyro_left.direction.xx,
                    frame.gyro_left.direction.xy,
                    frame.gyro_left.direction.xz,
                    frame.gyro_left.direction.yx,
                    frame.gyro_left.direction.yy,
                    frame.gyro_left.direction.yz,
                    frame.gyro_left.direction.zx,
                    frame.gyro_left.direction.zy,
                    frame.gyro_left.direction.zz,
                )
            )
            outf.write(
                struct.pack(
                    "<3f",
                    frame.gyro_left.ang_vel.x,
                    frame.gyro_left.ang_vel.y,
                    frame.gyro_left.ang_vel.z,
                )
            )
            outf.write(
                struct.pack(
                    "<9f",
                    frame.gyro_right.direction.xx,
                    frame.gyro_right.direction.xy,
                    frame.gyro_right.direction.xz,
                    frame.gyro_right.direction.yx,
                    frame.gyro_right.direction.yy,
                    frame.gyro_right.direction.yz,
                    frame.gyro_right.direction.zx,
                    frame.gyro_right.direction.zy,
                    frame.gyro_right.direction.zz,
                )
            )
            outf.write(
                struct.pack(
                    "<3f",
                    frame.gyro_right.ang_vel.x,
                    frame.gyro_right.ang_vel.y,
                    frame.gyro_right.ang_vel.z,
                )
            )

    outf.close()

    print("Script successfully generated")

    if ftp:
        ftp_config_file = open("ftp_config.json")
        ftp_config = json.load(ftp_config_file)
        ftp_config_file.close

        ftpC = FTP()
        ftpC.connect(host=ftp_config["ip"], port=int(ftp_config["port"]))
        ftpC.login(user=ftp_config["user"], passwd=ftp_config["passwd"])

        file = open(outfile, "rb")

        result = ftpC.storbinary("STOR SMO/tas/scripts/" + outfile, file)
        if result == "226 OK":
            print("Script successfully uploaded")
        else:
            print("FTP error")

        ftpC.quit()
