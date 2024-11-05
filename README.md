# POC ryujit (dotnet)-inspired Linear Scan Register Allocation

- Most of the interesting parts are in lsra.py
- ir.py contains code related to the tree-based intermediate representation (extremely simplified equivalent of the GenTree system in ryujit)
- stack_instruction.py contains code related to a small stack-based instruction set, as well as helper methods to convert it to ir
- main.py contains a demo

Resources :
- [https://github.com/dotnet/runtime/blob/main/docs/design/coreclr/jit/lsra-detail.md](https://github.com/dotnet/runtime/blob/main/docs/design/coreclr/jit/lsra-detail.md)
- [https://github.com/dotnet/runtime/blob/main/docs/design/coreclr/jit/ryujit-overview.md#reg-alloc](https://github.com/dotnet/runtime/blob/main/docs/design/coreclr/jit/ryujit-overview.md#reg-alloc)