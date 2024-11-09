# POC ryujit (dotnet)-inspired Linear Scan Register Allocation

## This project is being continued here : [https://github.com/PhilippeGSK/RLSRA](https://github.com/PhilippeGSK/RLSRA)

- Most of the interesting parts are in lsra.py
- ir.py contains code related to the tree-based intermediate representation (extremely simplified equivalent of the GenTree system in ryujit)
- stack_instruction.py contains code related to a small stack-based instruction set, as well as helper methods to convert it to ir
- main.py contains a demo

Resources :
- [https://github.com/dotnet/runtime/blob/main/docs/design/coreclr/jit/lsra-detail.md](https://github.com/dotnet/runtime/blob/main/docs/design/coreclr/jit/lsra-detail.md)
- [https://github.com/dotnet/runtime/blob/main/docs/design/coreclr/jit/ryujit-overview.md#reg-alloc](https://github.com/dotnet/runtime/blob/main/docs/design/coreclr/jit/ryujit-overview.md#reg-alloc)

Areas to improve :
- The operand reuse code is rather primitive and doesn't distinguish between lhs and rhs operands. It also doesn't take into account the fact that
some instructions might not be able to reuse operands for output
- The block execution order is, so far, just the order the blocks are in in the stack-based language. It might be a good idea to, for example,
sort the blocks by their likeliness to be executed
- Edges are not weighted
- Consider doing LSRA iterating through the trees in reverse like LuaJIT does?