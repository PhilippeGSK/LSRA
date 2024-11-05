from stack_instruction import *
from lsra import *
from ir import *

ins: list[StackInstruction] = [
    StackInstruction(StackInstructionKind.LdLocal, [0]),
    StackInstruction(StackInstructionKind.LdLocal, [0]),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.LdLocal, [0]),
    StackInstruction(StackInstructionKind.LdLocal, [0]),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.Ret, []),
]
fn = StackFunction(local_vars=5, instructions=ins)

ir = import_to_ir(fn)

try:
    Lsra().do_linear_scan(ir)
except Exception as e:
    ir.dump()
    raise e

ir.dump()