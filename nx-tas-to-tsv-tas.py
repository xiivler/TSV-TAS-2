import struct
import enum
import numpy as np
import math
import sys
import csv
from dataclasses import dataclass, field

RAD_TO_DEG = 180 / math.pi
DEG_TO_RAD = math.pi / 180

inpath = sys.argv[1]
outpath = sys.argv[2]

@dataclass
class Vector2f:
    r: float
    theta: float

    @staticmethod
    def zero():
        return Vector2f(0, 0)

'''
@dataclass
class Vector3f:
    x: float
    y: float
    z: float

    @staticmethod
    def zero():
        return Vector3f(0, 0, 0)


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
    direction: Matrix33f
    ang_vel: Vector3f

    @staticmethod
    def zero():
        return Gyro(Matrix33f.ident(), Vector3f.zero())
'''

@dataclass
class Frame:
    duration: int
    buttons: list[str]
    left_stick: Vector2f
    right_stick: Vector2f
    #accel_left: Vector3f
    #accel_right: Vector3f
    #gyro_left: Gyro
    #gyro_right: Gyro

    def to_array(self):
        arr = []
        if self.duration == 1:
            arr.append("")
        else:
            arr.append(self.duration)
        for button in self.buttons:
            arr.append(button)
        for i in range(max_buttons - len(self.buttons)):
            arr.append("")
        if (self.left_stick == Vector2f.zero()):
            arr.append("")
        elif (self.left_stick.r == 1):
            arr.append("ls(" + str(self.left_stick.theta) + ")")
        else:
            arr.append("ls(" + str(self.left_stick.r) + "; " + str(self.left_stick.theta) + ")")
        if (self.right_stick == Vector2f.zero()):
            arr.append("")
        elif (self.right_stick.r == 1):
            arr.append("rs(" + str(self.right_stick.theta) + ")")
        else:
            arr.append("rs(" + str(self.right_stick.r) + "; " + str(self.right_stick.theta) + ")")

        return arr

def toRoundedPolar(x, y):
    r = math.sqrt(x * x + y * y) / 32767
    theta = np.arctan2(y, x) * RAD_TO_DEG
    if (theta < 0):
        theta += 360

    r_rounded, theta_rounded = r, theta

    #try to round to simplest terms possible
    for r_decimalPlaces in range(4):
        for theta_decimalPlaces in range(5):
            #print(decimalPlaces)
            r_rounded_test = round(r, r_decimalPlaces)
            theta_rounded_test = round(theta, theta_decimalPlaces)
            #print(r_rounded_test)
            x_test = int(32767 * r_rounded_test * math.cos(theta_rounded_test * DEG_TO_RAD))
            y_test = int(32767 * r_rounded_test * math.sin(theta_rounded_test * DEG_TO_RAD))
            if x_test == x and y_test == y:
                r_rounded = r_rounded_test
                if theta_decimalPlaces == 0:
                    theta_rounded = int(theta_rounded_test)
                else:
                    theta_rounded = theta_rounded_test
                break

    return Vector2f(r_rounded, theta_rounded)

max_buttons = 0 #max buttons in a frame

frame_idx_old = -1

frames = []

with open(inpath) as infile:
    for line in infile:
        frame_idx, buttons, left_stick, right_stick = line.split()
        frame_idx = int(frame_idx)
        buttons = buttons.split(";")
        left_stick = left_stick.split(";")
        right_stick = right_stick.split(";")
        #accel_left = accel_left.split(";")
        #accel_right = accel_right.split(";")
        #gyro_dir_left = gyro_dir_left.split(";")
        #angvel_left = angvel_left.split(";")
        #gyro_dir_right = gyro_dir_right.split(";")
        #angvel_right = angvel_right.split(";")

        button_list = []
        for button in buttons:
            if button == "KEY_A": button_list.append("a")
            elif button == "KEY_B": button_list.append("b")
            elif button == "KEY_X": button_list.append("x")
            elif button == "KEY_Y": button_list.append("y")
            elif button == "KEY_L": button_list.append("l")
            elif button == "KEY_R": button_list.append("r")
            elif button == "KEY_ZL": button_list.append("zl")
            elif button == "KEY_ZR": button_list.append("zr")
            elif button == "KEY_PLUS": button_list.append("+")
            elif button == "KEY_MINUS": button_list.append("-")
            elif button == "KEY_DLEFT": button_list.append("dp-l")
            elif button == "KEY_DUP": button_list.append("dp-u")
            elif button == "KEY_DRIGHT": button_list.append("dp-r")
            elif button == "KEY_DDOWN": button_list.append("dp-d")
            elif button == "KEY_LSTICK": button_list.append("ls")
            elif button == "KEY_RSTICK": button_list.append("rs")

        if len(button_list) > max_buttons:
            max_buttons = len(button_list)

        ls_x, ls_y = int(left_stick[0]), int(left_stick[1])
        rs_x, rs_y = int(right_stick[0]), int(right_stick[1])

        if ls_x == 0 and ls_y == 0:
            left_stick = Vector2f.zero()
        else:
            left_stick = toRoundedPolar(ls_x, ls_y)

        if rs_x == 0 and rs_y == 0:
            right_stick = Vector2f.zero()
        else:
            right_stick = toRoundedPolar(rs_x, rs_y)

        #accel_left = Vector3f(*map(float, accel_left))
        #accel_right = Vector3f(*map(float, accel_right))

        #gyro_dir_left = Matrix33f(*map(float, gyro_dir_left))
        #angvel_left = Vector3f(*map(float, angvel_left))

        #gyro_dir_right = Matrix33f(*map(float, gyro_dir_right))
        #angvel_right = Vector3f(*map(float, angvel_right))

        #gyro_left = Gyro(gyro_dir_left, angvel_left)
        #gyro_right = Gyro(gyro_dir_right, angvel_right)

        numSkipped = frame_idx - frame_idx_old - 1

        #check for skipped empty frames
        if numSkipped > 0:           
            frame = Frame(numSkipped, [], Vector2f.zero(), Vector2f.zero())
            frames.append(frame)

        #check for repeated frames
        if frames[-1].buttons == button_list and frames[-1].left_stick == left_stick and frames[-1].right_stick == right_stick:
            frames[-1].duration += 1
        else:
            frame = Frame(1, button_list, left_stick, right_stick)
            frames.append(frame)

        frame_idx_old = frame_idx

infile.close()

outfile = open(outpath, "w")

tsv_writer = csv.writer(outfile, delimiter = '\t')

for frame in frames:
    tsv_writer.writerow(frame.to_array())