BUILD_DIR := build
GAME_DSK := $(BUILD_DIR)/brucelee.dsk

.PHONY: build run shot demo verify toolchain clean

# sources -> bootable raw .dsk: resource generators (font, strings,
# tiles, chambers, sprites, hud, music, title picture), MACRO-11
# modules concatenated per src/brucelee.list, assembled with
# bin/macro11, linked flat, disk laid out (program + title blobs)
build:
	python3 tools/build_brucelee.py $(GAME_DSK)

# build, then open a playable emulator window (SDL2, UKNCBTL core).
# It boots the firmware loader by itself; arrows move, ФИКС (LCtrl)
# = P1 fire, numpad Enter (RCtrl) = P2 fire, Enter starts.
run: build
	bin/ukncbtl/uknc-play --rom bin/ukncbtl/uknc_rom.bin --disk $(GAME_DSK)

# headless proof-of-life: boot to the game menu, screenshot it
shot: build
	python3 tools/uknc_control.py boot --shot tmp/run-menu.png

# start a game and walk right into chamber 1, screenshot it
demo: build
	python3 tools/uknc_control.py play ENTER RIGHT RIGHT RIGHT RIGHT \
	    --every 100 --wait 200 --shot tmp/run-demo.png

# resource round-trips, generator determinism, title encode, and a
# boot-to-gameplay smoke test in the headless emulator
verify: build
	python3 tools/verify_build.py

# rebuild macro11 and the headless emulator from source into bin/
# (compiles under tmp/, needs cc/make)
toolchain:
	python3 tools/build_toolchain.py

clean:
	rm -rf $(BUILD_DIR)
