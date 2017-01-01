tests: ./tests/test.asm
	./wla-dx-master/binaries/wla-gb -v -I tests/ -o tests/test.o tests/test.asm 
	./wla-dx-master/binaries/wlalink -d -v tests/test.linkfile tests/test.gb

clean:
	rm tests/*.o tests/*.gb