#!/bin/sh

fbdebug -m 4
fbdebug -m 0

p=/sys/class/graphics/fb0
cat $p/modes > $p/mode
