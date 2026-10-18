Main plaform: macOS ARM / iPad M2 no JIT, no high virtual memory requirements for ios compatibility

Graphics API: Metal or Vulkan/Spirv with MoltenVK
	Graphics backend should support 1080p full res 16:9 but also 4:3 modes / 16:10 / 16:10
	First focus on 1080p 16:9 native for the mvp
	
Selectable Framerate targets internally 60 Double Buffered / 120 FPS (ProMotion - variable and or fixed)

All assets should be provided by either an original NSP oder XCI dump, so everything stays in the legal zone.

Unity can be used, but transitioning away from the bloat / legacy 2019 version of Unity if possible / necessary would be ideal.

Original Save File compatibility so either a ryujiinx/yuzu/native switch dumped save files should be supported.


