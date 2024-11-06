from stack_instruction import *
from lsra import *
from ir import *

n = 10

ins: list[StackInstruction] = [
    StackInstruction(StackInstructionKind.Push, [0]),
    StackInstruction(StackInstructionKind.StLocal, [0]),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.StLocal, [1]),
    StackInstruction(StackInstructionKind.Push, [n]),
    StackInstruction(StackInstructionKind.StLocal, [3]),
    
    # 6:
    StackInstruction(StackInstructionKind.LdLocal, [3]),
    StackInstruction(StackInstructionKind.Push, [0]),
    StackInstruction(StackInstructionKind.Eq, []),
    StackInstruction(StackInstructionKind.Branch, [23, 10]),

    # 10:
    StackInstruction(StackInstructionKind.LdLocal, [0]),
    StackInstruction(StackInstructionKind.LdLocal, [1]),
    StackInstruction(StackInstructionKind.Add, []),
    StackInstruction(StackInstructionKind.StLocal, [2]),
    StackInstruction(StackInstructionKind.LdLocal, [1]),
    StackInstruction(StackInstructionKind.StLocal, [0]),
    StackInstruction(StackInstructionKind.LdLocal, [2]),
    StackInstruction(StackInstructionKind.StLocal, [1]),
    StackInstruction(StackInstructionKind.LdLocal, [3]),
    StackInstruction(StackInstructionKind.Push, [1]),
    StackInstruction(StackInstructionKind.Sub, []),
    StackInstruction(StackInstructionKind.StLocal, [3]),

    StackInstruction(StackInstructionKind.Jmp, [6]),

    # 23:
    StackInstruction(StackInstructionKind.LdLocal, [0]),
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