import bus
import pygame

class VIDEO(object):
    def __init__(self, bus, scale=4):
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

        self.bg_tiles = []
        for tile_idx in xrange(192):
            self.bg_tiles.append(self.tile_bitmap(self.vram_tile.tiles[tile_idx], self.vregs.bgp))

    def tile_bitmap(self, tile, palette):
        bitmap = pygame.Surface((8*self.scale, 8*self.scale),depth=8)
        bitmap.set_palette(map(lambda x: self.colors[x], palette))
        for pix_idx, pix in enumerate(tile):
            pix_x = 7 - (pix_idx % 8)
            pix_y = pix_idx / 8
            pix_x *= self.scale
            pix_y *= self.scale
            bitmap.fill(pix, (pix_x, pix_y, self.scale, self.scale))
        return bitmap
    
    def draw(self):
        for tile_idx in xrange(len(self.bg_tiles)):
            if self.vram_tile.tiles_changed[tile_idx]:
                self.bg_tiles[tile_idx] = self.tile_bitmap(self.vram_tile.tiles[tile_idx], self.vregs.bgp)
                self.vram_tile.tiles_changed[tile_idx] = False

        tile_map = self.vram_map_0.map

        x = 0
        y = 0
        scx = self.vregs.scx
        scy = self.vregs.scy

        for x in range(-1,160/8):
            for y in range(-1,144/8):
                map_x = (x - scx / 8) & 0x1F
                map_y = (y - scy / 8) & 0x1F
                map_idx = map_x + map_y * 32
                bitmap = self.bg_tiles[tile_map[map_idx]]
                self.window.blit(bitmap, ((x*8+scx%8)*self.scale, (y*8+scy%8)*self.scale))

        # for map_idx, tile_idx in enumerate(tile_map):
        #     bitmap = self.bg_tiles[tile_idx]
        #     tile_origin = [(scx + x * 8) * self.scale, (scy + y * 8) * self.scale]
        #     self.window.blit(bitmap, tile_origin)
            
        #     x += 1
        #     if x > 32:
        #         x = 0
        #         y += 1

        pygame.display.flip()


class VIDEO_REGS(bus.BUS_OBJECT):
    def __init__(self):
        super(VIDEO_REGS, self).__init__()

        self.bgp = [3,2,1,0]
        self.obp0 = [3,0,0,0]
        self.obp1 = [3,0,0,0]

        self.scx = 0
        self.scy = 0

    def bus_read(self, addr):
        if addr == 0: # FF40 - LCDC
            pass
        elif addr == 1: # FF41 - STAT
            pass
        elif addr == 2: # FF42 - SCY
            return self.scy
        elif addr == 3: # FF43 - SCX
            return self.scx
        elif addr == 4: # FF44 - LY
            pass
        elif addr == 5: # FF45 - LYC
            pass
        elif addr == 6: # FF46 - DMA
            pass
        elif addr == 7: # FF47 - BGP
            return reduce(lambda x,y: x<<2 | y, reversed(self.bgp))
        elif addr == 8: # FF48 - OBP0
            return reduce(lambda x,y: x<<2 | y, reversed(self.obp0))
        elif addr == 9: # FF49 - OBP1
            return reduce(lambda x,y: x<<2 | y, reversed(self.obp1))
        elif addr == 10: # FF4A - WY
            pass
        elif addr == 11: # FF4B - WX
            pass
        else:
            raise Exception("video driver doesn't know WHAT the fuck to do")

    def bus_write(self, addr, value):
        if addr == 0: # FF40 - LCDC
            pass
        elif addr == 1: # FF41 - STAT
            pass
        elif addr == 2: # FF42 - SCY
            self.scy = value & 0xFF
        elif addr == 3: # FF43 - SCX
            self.scx = value & 0xFF
        elif addr == 4: # FF44 - LY
            pass
        elif addr == 5: # FF45 - LYC
            pass
        elif addr == 6: # FF46 - DMA
            pass
        elif addr == 7: # FF47 - BGP
            self.bgp = map(lambda x: (value >> x) & 0x2, [0,2,4,6])
        elif addr == 8: # FF48 - OBP0
            self.obp0 = map(lambda x: (value >> x) & 0x2, [0,2,4,6])
        elif addr == 9: # FF49 - OBP1
            self.obp1 = map(lambda x: (value >> x) & 0x2, [0,2,4,6])
        elif addr == 10: # FF4A - WY
            pass
        elif addr == 11: # FF4B - WX
            pass
        else:
            raise Exception("video driver doesn't know WHAT the fuck to do")


class VIDEO_TILE_RAM(bus.BUS_OBJECT):
    def __init__(self):
        super(VIDEO_TILE_RAM, self).__init__()
        self.tiles = [[0]*(8*8)]*192
        self.tiles_changed = [False]*192

        self.tiles[0] = [
            0,0,0,0,0,0,0,0,
            0,2,0,0,0,0,3,0,
            0,0,0,0,0,0,0,0,
            0,0,0,0,0,0,0,0,
            0,0,0,0,0,0,0,0,
            0,0,0,0,0,0,0,0,
            0,1,0,0,0,0,0,0,
            0,0,0,0,0,0,0,0,
        ]

        self.tiles[1] = [
            0,0,1,1,1,0,0,0,
            0,1,1,1,1,1,0,0,
            1,1,2,1,2,1,1,0,
            1,3,1,1,1,3,1,0,
            1,3,1,3,1,3,1,0,
            0,1,3,1,3,1,0,0,
            0,0,1,1,1,0,0,0,
            0,0,0,0,0,0,0,0,
        ]


    def bus_read(self, addr):
        value = 0
        tile_idx = addr/16
        pix_base = ((addr - tile_idx) / 2) * 8
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
        tile_idx = addr/16
        pix_base = ((addr - tile_idx) / 2) * 8
        tile = self.tiles[tile_idx]
        pix_bit = addr % 2
        if pix_bit:
            value = value << 1
        for pix_idx in xrange(pix_base, pix_base+8):
            if pix_bit:
                tile[pix_idx] = (tile[pix_idx] & 0x2) | (value & 0x2)
            else:
                tile[pix_idx] = (tile[pix_idx] & 0x1) | (value & 0x1)
            value = value >> 1

        self.tiles_changed[tile_idx] = True


class VIDEO_MAP_RAM(bus.BUS_OBJECT):
    def __init__(self):
        super(VIDEO_MAP_RAM, self).__init__()
        self.map = [0]*32*32
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


class VIDEO_OAM(bus.BUS_OBJECT):
    def __init__(self):
        super(VIDEO_OAM, self).__init__()

    def bus_read(self, addr):
        pass

    def bus_write(self, addr, value):
        pass
