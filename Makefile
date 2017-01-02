tests: ./tests/test.asm ./tests/timer_int.asm
	./wla-dx-master/binaries/wla-gb -v -I tests/ -o tests/test.o tests/test.asm 
	./wla-dx-master/binaries/wlalink -d -v tests/test.linkfile tests/test.gb

	./wla-dx-master/binaries/wla-gb -v -I tests/ -o tests/timer_int.o tests/timer_int.asm 
	./wla-dx-master/binaries/wlalink -d -v tests/timer_int.linkfile tests/timer_int.gb


clean:
	rm tests/*.o tests/*.gb