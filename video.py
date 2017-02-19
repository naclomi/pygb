import bus
import pygame
import util

# TODO: For HBLANK, maybe speculatively draw the whole screen right after
# vblank and then just leave the backend idle while the video mode cycles,
# and then if any vram/regs get modified before the next vblank we
# speculatively draw the screen from that scanline down and blit it onto
# the original screen?
# and regardless only flip at the start of the next vblank?

class VIDEO(object):
    def __init__(self, bus, scale=4):
        self.T_mode2 = 19e-6
        self.T_mode3 = 41e-6
        self.T_mode0 = 48.6e-6
        self.T_mode1 = 1.08e-3
        self.T_refresh = (1/59.7)

        self.T_mode2_edge = self.T_mode2
        self.T_mode3_edge = self.T_mode2 + self.T_mode3
        self.T_mode0_edge = self.T_mode2 + self.T_mode3 + self.T_mode0
        self.T_scanline = self.T_mode0_edge

        # TODO: this *should* be 160, why doesn't that work??
        self.T_dma = 140e-6

        self.bus = bus
        self.scale = scale

        self.window = pygame.display.set_mode((160*self.scale, 144*self.scale))
        self.colors = [
            pygame.Color(0xFC, 0xFC, 0xFC, 0xFF),
            pygame.Color(0xBC, 0xBC, 0xBC, 0xFF),
            pygame.Color(0x74, 0x74, 0x74, 0xFF),
            pygame.Color(0x00, 0x00, 0x00, 0xFF),
        ]
        self.window.fill(self.colors[3])

        self.vregs = VIDEO_REGS()
        bus.attach(self.vregs, 0xFF40, 0xFF4B)

        self.vram_tile = VIDEO_TILE_RAM()
        bus.attach(self.vram_tile, 0x8000, 0x97FF)

        self.vram_map_0 = VIDEO_MAP_RAM()
        bus.attach(self.vram_map_0, 0x9800, 0x9BFF)

        self.vram_map_1 = VIDEO_MAP_RAM()
        bus.attach(self.vram_map_1, 0x9C00, 0x9FFF)

        self.vram_oam = VIDEO_OAM()
        bus.attach(self.vram_oam, 0xFE00, 0xFE9F)

        self.bg_tiles = [None] * self.vram_tile.N_tiles
        self.oam_tiles = [None] * len(self.vram_oam.sprites)
        self.update_bg_tiles()
        self.update_oam()

        self.frame = 0

        self.enabled = False
        self.display_clock = 0.0
        self.dma_clock = 0.0

    def dma_active(self):
        return self.dma_clock > 0

    def render_bitmap(self, tile, palette):
        bitmap = pygame.Surface((8*self.scale, len(tile) / 8 * self.scale), depth=8)
        bitmap.set_palette(map(lambda x: self.colors[x], palette))
        # Color 0 is transparent on sprites. For tile maps, we'll also have
        # it be transparent but paint the screen with this color right after
        # clearing it to allow a semi-transparent effect for low-priority
        # sprites to show through
        bitmap.set_colorkey(0)
        for pix_idx, pix in enumerate(tile):
            pix_x = 7 - (pix_idx % 8)
            pix_y = pix_idx / 8
            pix_x *= self.scale
            pix_y *= self.scale
            bitmap.fill(pix, (pix_x, pix_y, self.scale, self.scale))
        return bitmap
    
    def update_oam(self):
        size = self.vregs.sprite_size
        for sprite in self.vram_oam.sprites:
            if (sprite.rerender or
                (size == 0 and self.vram_tile.tiles_changed[sprite.tile_idx]) or
                (size == 1 and self.vram_tile.tiles_changed[sprite.tile_idx & 0xFE]) or
                (size == 1 and self.vram_tile.tiles_changed[(sprite.tile_idx & 0xFE) + 1])):
                if size == 0:
                    tile = self.vram_tile.tiles[sprite.tile_idx]
                else:
                    tile = self.vram_tile.tiles[sprite.tile_idx & 0xFE]
                    tile += self.vram_tile.tiles[(sprite.tile_idx & 0xFE) + 1]

                palette = self.vregs.obp1 if sprite.palette == 1 else self.vregs.obp0
                self.oam_tiles[sprite.idx] = self.render_bitmap(tile, palette)
                if sprite.h_flip or sprite.v_flip:
                    self.oam_tiles[sprite.idx] = pygame.transform.flip(self.oam_tiles[sprite.idx], sprite.h_flip, sprite.v_flip)
                sprite.rerender = False
            elif sprite.palette == 0 and self.vregs.obp0_changed:
                self.oam_tiles[sprite.idx].set_palette(map(lambda x: self.colors[x], self.vregs.obp0))
            elif sprite.palette == 1 and self.vregs.obp1_changed:
                self.oam_tiles[sprite.idx].set_palette(map(lambda x: self.colors[x], self.vregs.obp1))
        self.vregs.obp0_changed = False
        self.vregs.obp1_changed = False

    def update_bg_tiles(self):
        for tile_idx in xrange(len(self.bg_tiles)):
            if self.vram_tile.tiles_changed[tile_idx]:
                self.bg_tiles[tile_idx] = self.render_bitmap(
                    self.vram_tile.tiles[tile_idx],
                    self.vregs.bgp
                )
            elif self.vregs.bgp_changed:
                self.bg_tiles[tile_idx].set_palette(map(lambda x: self.colors[x], self.vregs.bgp))
        self.vregs.bgp_changed = False

    def draw(self):        
        self.window.fill(self.colors[0])

        if self.vregs.display_enable:

            # Fill with color 0 before drawing low-priority sprites
            if self.vregs.bg_enable or self.vregs.window_enable:
                self.update_bg_tiles()
                # TODO: is this correct if bg is disabled and window is not
                # at origin?
                self.window.fill(self.colors[self.vregs.bgp[0]])

            scx = 256 - self.vregs.scx
            scy = 256 - self.vregs.scy
            wx = 256 - self.vregs.wx
            wy = 256 - self.vregs.wy
            data_select = self.vregs.map_data

            # Draw background
            if self.vregs.bg_enable:
                if self.vregs.bg_map == 0:
                    tile_map = self.vram_map_0.map 
                else:
                    tile_map = self.vram_map_1.map

                x = 0
                y = 0
                for x in range(-1,160/8):
                    for y in range(-1,144/8):
                        map_x = (x - scx / 8) & 0x1F
                        map_y = (y - scy / 8) & 0x1F
                        map_idx = map_x + map_y * 32
                        if data_select:
                            tile_idx = tile_map[map_idx]
                        else:
                            tile_idx = 0x80 + (((tile_map[map_idx]&0xFF)-128)&0xFF)
                        bitmap = self.bg_tiles[tile_idx]
                        self.window.blit(bitmap, (
                            (x*8+scx%8)*self.scale, 
                            (y*8+scy%8)*self.scale
                        ))

            # Draw low-priority sprites
            if self.vregs.sprite_enable:
                self.update_oam()

                scan_sprites = []
                for sprite in self.vram_oam.sprites:
                    if sprite.priority == 0 and 0 < sprite.y <= 160:
                        scan_sprites.append(sprite)
                scan_sprites.sort(key=lambda spr: (-spr.x, -spr.idx))
                for sprite in scan_sprites:
                    bitmap = self.oam_tiles[sprite.idx]
                    self.window.blit(bitmap, (
                        (sprite.x - 8) * self.scale, 
                        (sprite.y - 16) * self.scale
                    ))

            # Draw window
            if self.vregs.window_enable and wx <= 166 and wy <= 143 :
                if self.vregs.window_map == 0:
                    tile_map = self.vram_map_0.map 
                else:
                    tile_map = self.vram_map_1.map
                    
                x = 0
                y = 0
                data_select = self.vregs.map_data

                # Hmmmmmmmm, wrt window:
                #  If the window is used and a scan line interrupt disables
                # it (either by writing to LCDC or by setting WX > 166)
                # and a scan line interrupt a little later on enables it
                # then the window will resume appearing on the screen at the
                # exact position of the window where it left off earlier.
                # This way, even if there are only 16 lines of useful graphics
                # in the window, you could display the first 8 lines at the
                # top of the screen and the next 8 lines at the bottom if
                # you wanted to do so.
                #
                #  WX may be changed during a scan line interrupt (to either
                # cause a graphic distortion effect or to disable the window
                # (WX>166) ) but changes to WY are not dynamic and won't
                # be noticed until the next screen redraw.

                for x in range(-1,160/8):
                    for y in range(-1,144/8):
                        map_idx = x + y * 32
                        if data_select:
                            tile_idx = tile_map[map_idx]
                        else:
                            tile_idx = 0x80 + (((tile_map[map_idx]&0xFF)-128)&0xFF)
                        bitmap = self.bg_tiles[tile_idx]
                        self.window.blit(bitmap, (
                            (x*8+wx-7)*self.scale, 
                            (y*8+wy)*self.scale
                        ))

            # Draw high-priority sprites
            if self.vregs.sprite_enable:
                scan_sprites = []
                for sprite in self.vram_oam.sprites:
                    if sprite.priority == 1 and 0 < sprite.y <= 160:
                        scan_sprites.append(sprite)
                scan_sprites.sort(key=lambda spr: (-spr.x, -spr.idx))
                for sprite in scan_sprites:
                    bitmap = self.oam_tiles[sprite.idx]
                    self.window.blit(bitmap, (
                        (sprite.x - 8) * self.scale, 
                        (sprite.y - 16) * self.scale
                    ))

            for tile_idx in range(len(self.vram_tile.tiles_changed)):
                self.vram_tile.tiles_changed[tile_idx] = False

        pygame.display.flip()

    def advance(self, delta):

        # TODO: implement scanline redraw

        # Handle OAM DMA
        if self.dma_active():
            # TODO: good for debugging, but delete eventually:
            # print "dma clock", util.time_str(self.dma_clock)
            self.dma_clock -= delta
            if self.dma_clock <= 0:
                self.dma_clock = 0
                self.vregs.dma_base = None
        else:
            if self.vregs.dma_base is not None:
                # TODO: good for debugging, but delete eventually:
                # print "dma clock", util.time_str(self.dma_clock)
                self.dma_clock = self.T_dma - delta
                self.vram_oam.dma(self.vregs.dma_base)

        if self.vregs.display_enable:
            self.enabled = True

            self.display_clock += delta
            scan_clock = self.display_clock % self.T_scanline

            # Wrap display clock if we've refreshed the screen
            if self.display_clock >= self.T_refresh:
                    self.draw()
                    self.frame += 1
                    self.display_clock -= self.T_refresh

            # Emulate display state machine
            if self.display_clock >= self.T_scanline * 144:
                # V-Blank
                if self.vregs.mode != 1:
                    self.vregs.mode = 1

                    self.vram_oam.bus_enabled = True
                    self.vram_tile.bus_enabled = True
                    self.vram_map_0.bus_enabled = True
                    self.vram_map_1.bus_enabled = True

                    # Trigger an interrupt
                    # TODO: pull these magic numbers out somewhere
                    IF_state = self.bus.read(0xFF0F)
                    IF_state |= 0x1
                    if self.vregs.v_blank_int:
                        IF_state |= 0x2
                    self.bus.write(0xFF0F, IF_state)

            elif scan_clock <= self.T_mode2_edge:
                # OAM
                if self.vregs.mode != 2:
                    self.vregs.mode = 2

                    self.vram_oam.bus_enabled = False
                    self.vram_tile.bus_enabled = True
                    self.vram_map_0.bus_enabled = True
                    self.vram_map_1.bus_enabled = True

                    if self.vregs.oam_int:
                        # Trigger an interrupt
                        # TODO: pull these magic numbers out somewhere
                        IF_state = self.bus.read(0xFF0F)
                        IF_state |= 0x2
                        self.bus.write(0xFF0F, IF_state)
            elif scan_clock <= self.T_mode3_edge:
                # OAM+VRAM
                if self.vregs.mode != 3:
                    self.vregs.mode = 3

                    self.vram_oam.bus_enabled = False
                    self.vram_tile.bus_enabled = False
                    self.vram_map_0.bus_enabled = False
                    self.vram_map_1.bus_enabled = False
            elif scan_clock <= self.T_mode0_edge:
                # H-Blank
                if self.vregs.mode != 0:
                    self.vregs.mode = 0

                    self.vram_oam.bus_enabled = True
                    self.vram_tile.bus_enabled = True
                    self.vram_map_0.bus_enabled = True
                    self.vram_map_1.bus_enabled = True

                    if self.vregs.h_blank_int:
                        # Trigger an interrupt
                        # TODO: pull these magic numbers out somewhere
                        IF_state = self.bus.read(0xFF0F)
                        IF_state |= 0x2
                        self.bus.write(0xFF0F, IF_state)

            # Update LY and check if we should trigger the coincidence interrupt
            cur_ly = int(self.display_clock / self.T_scanline)
            if self.vregs.ly != cur_ly:
                self.vregs.ly = cur_ly
            coincidence = self.vregs.ly == self.vregs.lyc
            if coincidence != self.vregs.coincidence_flag:
                self.vregs.coincidence_flag = coincidence
                if coincidence and self.vregs.coincidence_int:
                    # Trigger an interrupt
                    # TODO: pull these magic numbers out somewhere
                    IF_state = self.bus.read(0xFF0F)
                    IF_state |= 0x2
                    self.bus.write(0xFF0F, IF_state)
        else:
            if self.enabled:
                self.enabled = False

                # Reset state machine
                self.display_clock = 0
                
                # Reset STAT
                self.vregs.mode = 0
                self.vregs.ly = 0
                self.vregs.coincidence_flag = self.vregs.lyc == 0

                # Force RAM ports open
                self.vram_oam.bus_enabled = True
                self.vram_tile.bus_enabled = True
                self.vram_map_0.bus_enabled = True
                self.vram_map_1.bus_enabled = True

                self.draw()

class VIDEO_REGS(bus.BUS_OBJECT):
    def __init__(self):
        super(VIDEO_REGS, self).__init__()

        # STAT flags
        self.mode = 0
        self.coincidence_flag = 0
        self.h_blank_int = 0
        self.v_blank_int = 0
        self.oam_int = 0
        self.coincidence_int = 0

        # LY coincidence
        self.ly = 0
        self.lyc = 0

        # DMA request
        self.dma_base = None

        # LCDC flags
        self.display_enable = 1
        self.window_map = 0
        self.window_enable = 0
        self.map_data = 1
        self.bg_map = 0
        self.sprite_size = 0
        self.sprite_enable = 1
        self.bg_enable = 1

        # Palettes
        self.bgp = [3,2,1,0]
        self.bgp_changed = False
        self.obp0 = [3,2,1,0]
        self.obp0_changed = False
        self.obp1 = [3,0,1,2]
        self.obp1_changed = False

        # BG scroll
        self.scx = 0
        self.scy = 0

        # Window control
        self.wx = 0
        self.wy = 0

        self.reset()

    def reset(self):
        self.display_enable = 1
        self.window_map = 0
        self.window_enable = 0
        self.map_data = 1
        self.bg_map = 0
        self.sprite_size = 0
        self.sprite_enable = 0
        self.bg_enable = 1

        self.scx = 0
        self.scy = 0

        self.lyc = 0

        self.bgp = [0, 3, 3, 3]
        self.bgp_changed = True

        self.obp0 = [3, 3, 3, 3]
        self.obp0_changed = True

        self.obp1 = [3, 3, 3, 3]
        self.obp1_changed = True

        self.wx = 0
        self.wy = 0

    def bus_read(self, addr):
        if addr == 0: # FF40 - LCDC
            val = 0
            val |= self.display_enable << 7
            val |= self.window_map << 6
            val |= self.window_enable << 5
            val |= self.map_data << 4
            val |= self.bg_map << 3
            val |= self.sprite_size << 2
            val |= self.sprite_enable << 1
            val |= self.bg_enable << 0
            return val
        elif addr == 1: # FF41 - STAT
            val = 0
            val |= self.mode
            val |= self.coincidence_flag << 2
            val |= self.h_blank_int << 3
            val |= self.v_blank_int << 4
            val |= self.oam_int << 5
            val |= self.coincidence_int << 6
            return val
        elif addr == 2: # FF42 - SCY
            return self.scy
        elif addr == 3: # FF43 - SCX
            return self.scx
        elif addr == 4: # FF44 - LY
            return self.ly
        elif addr == 5: # FF45 - LYC
            return self.lyc
        elif addr == 6: # FF46 - DMA
            return self.dma_base if self.dma_base is not None else 0x00
        elif addr == 7: # FF47 - BGP
            return reduce(lambda x,y: x<<2 | y, reversed(self.bgp))
        elif addr == 8: # FF48 - OBP0
            return reduce(lambda x,y: x<<2 | y, reversed(self.obp0))
        elif addr == 9: # FF49 - OBP1
            return reduce(lambda x,y: x<<2 | y, reversed(self.obp1))
        elif addr == 10: # FF4A - WY
            return self.wy
        elif addr == 11: # FF4B - WX
            return self.wx
        else:
            raise Exception("video driver doesn't know WHAT the fuck to do")

    def bus_write(self, addr, value):
        if addr == 0: # FF40 - LCDC
            self.display_enable = ((value >> 7) & 0x1) != 0
            self.window_map = ((value >> 6) & 0x1) != 0
            self.window_enable = ((value >> 5) & 0x1) != 0
            self.map_data = ((value >> 4) & 0x1) != 0
            self.bg_map = ((value >> 3) & 0x1) != 0
            self.sprite_size = ((value >> 2) & 0x1) != 0
            self.sprite_enable = ((value >> 1) & 0x1) != 0
            self.bg_enable = ((value >> 0) & 0x1) != 0
        elif addr == 1: # FF41 - STAT
            self.h_blank_int = ((value >> 3) & 0x1) != 0
            self.v_blank_int = ((value >> 4) & 0x1) != 0
            self.oam_int = ((value >> 5) & 0x1) != 0
            self.coincidence_int = ((value >> 6) & 0x1) != 0
        elif addr == 2: # FF42 - SCY
            self.scy = value & 0xFF
        elif addr == 3: # FF43 - SCX
            self.scx = value & 0xFF
        elif addr == 4: # FF44 - LY
            pass
        elif addr == 5: # FF45 - LYC
            self.lyc = value & 0xFF
        elif addr == 6: # FF46 - DMA
            self.dma_base = value << 8
        elif addr == 7: # FF47 - BGP
            self.bgp_changed = True
            self.bgp = map(lambda x: (value >> x) & 0x3, [0,2,4,6])
        elif addr == 8: # FF48 - OBP0
            self.obp0_changed = True
            self.obp0 = map(lambda x: (value >> x) & 0x3, [0,2,4,6])
        elif addr == 9: # FF49 - OBP1
            self.obp1_changed = True
            self.obp1 = map(lambda x: (value >> x) & 0x3, [0,2,4,6])
        elif addr == 10: # FF4A - WY
            self.wy = value & 0xFF
        elif addr == 11: # FF4B - WX
            self.wx = value & 0xFF
        else:
            raise Exception("video driver doesn't know WHAT the fuck to do")


class VIDEO_TILE_RAM(bus.BUS_OBJECT):
    def __init__(self):
        super(VIDEO_TILE_RAM, self).__init__()
        
        self.N_tiles = 384
        self.tiles = [[0]*(8*8) for _ in range(self.N_tiles)]
        self.tiles_changed = [True]*self.N_tiles

        # TODO: delete these some day:
        # self.tiles[0] = [
        #     0,0,0,0,0,0,0,0,
        #     0,2,0,0,0,0,3,0,
        #     0,0,0,0,0,0,0,0,
        #     0,0,0,0,0,0,0,0,
        #     0,0,0,0,0,0,0,0,
        #     0,0,0,0,0,0,0,0,
        #     0,1,0,0,0,0,0,0,
        #     0,0,0,0,0,0,0,0,
        # ]
        # self.tiles[1] = [
        #     0,0,1,1,1,0,0,0,
        #     0,1,1,1,1,1,0,0,
        #     1,1,2,1,2,1,1,0,
        #     1,3,1,1,1,3,1,0,
        #     1,3,1,3,1,3,1,0,
        #     0,1,3,1,3,1,0,0,
        #     0,0,1,1,1,0,0,0,
        #     0,0,0,0,0,0,0,0,
        # ]

    def ascii_art(self, tile_idx):
        tile = self.tiles[tile_idx]
        for x in range(8):
            print "".join(map(str, tile[x*8:(x+1)*8]))

    def bus_read(self, addr):
        value = 0
        tile_idx = addr / 16
        pix_base = ((addr % 16) / 2) * 8
        tile = self.tiles[tile_idx]
        pix_bit = addr % 2
        for pix_idx in xrange(pix_base, pix_base+8):
            if pix_bit:
                value |= (tile[pix_idx] & 0x2) << (pix_idx-pix_base)
            else:
                value |= (tile[pix_idx] & 0x1) << (pix_idx-pix_base)
                tile[pix_idx] = (tile[pix_idx] & 0x1) | (value & 0x1)
        if pix_bit:
            value = value >> 1
        return value

    def bus_write(self, addr, value):
        tile_idx = addr / 16
        pix_base = ((addr % 16) / 2) * 8
        tile = self.tiles[tile_idx]
        pix_bit = addr % 2
        if pix_bit:
            value = value << 1
        for pix_idx in xrange(pix_base, pix_base+8):
            if pix_bit:
                tile[pix_idx] = (tile[pix_idx] & 0x1) | (value & 0x2)
            else:
                tile[pix_idx] = (tile[pix_idx] & 0x2) | (value & 0x1)
            value = value >> 1

        self.tiles_changed[tile_idx] = True


class VIDEO_MAP_RAM(bus.BUS_OBJECT):
    def __init__(self):
        super(VIDEO_MAP_RAM, self).__init__()
        self.map = [0]*32*32

        # TODO: this is probably debug code? should probably remove it
        for x in range (32):
            self.map[x + x*32] = 1
        self.map[1] = 1
        self.map[2] = 1
        self.map[-2] = 1
        self.map[-3] = 1

    def bus_read(self, addr):
        return self.map[addr]

    def bus_write(self, addr, value):
        self.map[addr] = value


class SPRITE(object):
    def __init__(self, idx):
        self.x = 0
        self.y = 0
        self.tile_idx = 0
        self.idx = idx

        self.priority = 0
        self.h_flip = 0
        self.v_flip = 0
        self.palette = 0

        self.rerender = True

    def read(self, addr):
        if addr == 0:
            return self.y
        elif addr == 1:
            return self.x
        elif addr == 2:
            return self.tile_idx
        elif addr == 3:
            val = 0
            val |= self.palette << 4
            val |= self.h_flip << 5
            val |= self.v_flip << 6
            val |= self.priority << 7
            return val
        else: 
            raise Exception("sprite doesn't know WHAT the fuck to do")

    def write(self, addr, value):
        if addr == 0:
            self.y = value & 0xFF
        elif addr == 1:
            self.x = value & 0xFF
        elif addr == 2:
            self.rerender = True
            self.tile_idx = value & 0xFF
        elif addr == 3:
            self.rerender = True
            self.palette = (value >> 4) & 0x01
            self.h_flip = (value >> 5) & 0x01
            self.v_flip = (value >> 6) & 0x01
            self.priority = (value >> 7) & 0x01
        else: 
            raise Exception("sprite doesn't know WHAT the fuck to do")


class VIDEO_OAM(bus.BUS_OBJECT):
    def __init__(self):
        super(VIDEO_OAM, self).__init__()
        self.sprites = [SPRITE(x) for x in range(40)]

        # TODO: delete these some day:
        # self.sprites[3].x = 40
        # self.sprites[3].y = 40
        # self.sprites[3].tile_idx = 1
        # self.sprites[3].v_flip = 1
        # self.sprites[3].priority = 1        
        # self.sprites[4].x = 50
        # self.sprites[4].y = 40
        # self.sprites[4].tile_idx = 1
        # self.sprites[4].v_flip = 1
        # self.sprites[4].palette = 1
        # self.sprites[4].priority = 0

    def dma(self, dma_base):
        ptr = dma_base
        for sprite in self.sprites:
            sprite.write(0, self.bus.read(ptr, force=True))
            sprite.write(1, self.bus.read(ptr+1, force=True))
            sprite.write(2, self.bus.read(ptr+2, force=True))
            sprite.write(3, self.bus.read(ptr+3, force=True))
            ptr += 4

    def bus_read(self, addr):
        return self.sprites[addr / 4].read(addr % 4)

    def bus_write(self, addr, value):
        self.sprites[addr / 4].write(addr % 4, value)
