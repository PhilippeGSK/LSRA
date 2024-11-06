import enum
import dataclasses
from ir import *

class StackInstructionKind(enum.Enum):
    LdLocal = enum.auto()
    StLocal = enum.auto()
    Push = enum.auto()
    Pop = enum.auto()
    Add = enum.auto()
    Sub = enum.auto()
    Mul = enum.auto()
    Div = enum.auto()
    Eq = enum.auto()
    Jmp = enum.auto()
    Branch = enum.auto()
    Ret = enum.auto()

@dataclasses.dataclass
class StackInstruction:
    kind: StackInstructionKind
    operands: list

@dataclasses.dataclass
class StackFunction:
    local_vars: int
    instructions: list[StackInstruction]

def import_to_ir(fn: StackFunction) -> Ir:
    blocks = BasicBlockList()
    current_block = blocks.first
    tree_stack: list[Tree] = []

    def fold(kind: TreeKind, n: int, operands: list) -> None:
        nonlocal tree_stack
        if (n > len(tree_stack)):
            raise Exception("Not enough stack operands")
        l = len(tree_stack)
        res = tree_stack[l - n:]
        tree_stack = tree_stack[:l - n]

        new_tree = Tree(kind=kind, subtrees=res, operands=operands, parent=None)
        for subtree in new_tree.subtrees:
            subtree.parent = new_tree

        tree_stack.append(new_tree)
    
    last_i_ins = len(fn.instructions) - 1
    i_stmt_start = 0

    for i_ins, ins in enumerate(fn.instructions):
        match ins.kind:
            case StackInstructionKind.LdLocal:
                fold(TreeKind.LdLocal, 0, ins.operands)

            case StackInstructionKind.StLocal:
                fold(TreeKind.StLocal, 1, ins.operands)
                current_block.append_tree(i_stmt_start, tree_stack.pop())
                i_stmt_start = i_ins + 1
                if tree_stack != []: raise Exception("Leftover stack operands")

            case StackInstructionKind.Push:
                fold(TreeKind.Const, 0, ins.operands)

            case StackInstructionKind.Pop:
                fold(TreeKind.Discard, 1, [])
                current_block.append_tree(i_stmt_start, tree_stack.pop())
                i_stmt_start = i_ins + 1
                if tree_stack != []: raise Exception("Leftover stack operands")

            case StackInstructionKind.Add:
                fold(TreeKind.BinOp, 2, [Operator.Add])

            case StackInstructionKind.Sub:
                fold(TreeKind.BinOp, 2, [Operator.Sub])

            case StackInstructionKind.Mul:
                fold(TreeKind.BinOp, 2, [Operator.Mul])

            case StackInstructionKind.Div:
                fold(TreeKind.BinOp, 2, [Operator.Div])

            case StackInstructionKind.Eq:
                fold(TreeKind.BinOp, 2, [Operator.Eq])

            case StackInstructionKind.Jmp:
                target = blocks.get_or_insert_block_at(ins.operands[0])
                fold(TreeKind.Jmp, 0, [target])
                current_block.append_tree(i_stmt_start, tree_stack.pop())
                i_stmt_start = i_ins + 1
                if tree_stack != []: raise Exception("Leftover stack operands")
                if (i_ins == last_i_ins): break
                current_block = blocks.get_or_insert_block_at(i_ins + 1)

            case StackInstructionKind.Branch:
                if_target = blocks.get_or_insert_block_at(ins.operands[0])
                else_target = blocks.get_or_insert_block_at(ins.operands[1])
                fold(TreeKind.Branch, 1, [if_target, else_target])
                current_block.append_tree(i_stmt_start, tree_stack.pop())
                i_stmt_start = i_ins + 1
                if tree_stack != []: raise Exception("Leftover stack operands")
                if (i_ins == last_i_ins): break
                current_block = blocks.get_or_insert_block_at(i_ins + 1)

            case StackInstructionKind.Ret:
                fold(TreeKind.Ret, 1, [])
                current_block.append_tree(i_stmt_start, tree_stack.pop())
                i_stmt_start = i_ins + 1
                if (i_ins == last_i_ins): break
                current_block = blocks.get_or_insert_block_at(i_ins + 1)
        
        if (i_ins == last_i_ins):
            raise Exception("Illegal terminator")

    result = Ir(blocks=blocks, local_vars=fn.local_vars)
    result.recompute_predecessors()
    result.reindex()
    return result