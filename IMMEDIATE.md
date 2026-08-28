[x] change the language: in range a…b the values must exclude b, matching Python's behavior.  Update all sources for the new semantic,
    remove now unnecessary tests, update the specification
[x] add test case to check that using a…b with a and b being numeric values with different units is rejected
[x] fix the capture-as-a-read warning divergence in ngplc
