from __future__ import annotations
import dataclasses
import enum
from typing import *
from lsra import RegSpill, RegRestore, RegMove, CBActiveInterval
import itertools

class Operator(enum.Enum):
    Add = enum.auto()
    Sub = enum.auto()
    Mul = enum.auto()
    Div = enum.auto()

    Eq = enum.auto()

class TreeKind(enum.Enum):
    LdLocal = enum.auto()
    StLocal = enum.auto()
    Const = enum.auto()
    Discard = enum.auto()
    BinOp = enum.auto()

    # Reserved for terminals
    Ret = enum.auto()
    Branch = enum.auto()
    Jmp = enum.auto()

@dataclasses.dataclass
class Tree:
    kind: TreeKind
    subtrees: list[Tree]
    operands: list
    parent: Tree | None
    block: BasicBlock

    # Assigned during Ir.reindex
    ir_idx: int = 0
    # Assigned during Lsra.do_linear_scan
    reg: int = -1
    spills: list[RegSpill] = dataclasses.field(default_factory=list)
    restores: list[RegRestore] = dataclasses.field(default_factory=list)
    
    def tree_execution_order(self) -> Iterable[Tree]:
        for subtree in self.subtrees:
            for tree in subtree.tree_execution_order():
                yield tree
        
        yield self

    def dump(self, indent_level: int = 0):
        for tree in self.subtrees:
            tree.dump(indent_level + 4)

        for spill in self.spills:
            print(" " * indent_level + str(spill))
        for restore in self.restores:
            print(" " * indent_level + str(restore))
        reg = "" if self.parent == None else "(r" + str(self.reg) + ") "
        print(
            " " * indent_level +
            "[" + str(self.ir_idx) + "] " +
            reg +
            self.kind.name +
            "(" + ", ".join(map(str, self.operands)) + ")"
        )

@dataclasses.dataclass
class Statement:
    il_idx: int
    next_statement: Statement | None
    prev_statement: Statement | None
    tree: Tree

@dataclasses.dataclass
class BlockEdge:
    target: BasicBlock

    # Assigned during Lsra.do_linear_scan
    spills: list[RegSpill] = dataclasses.field(default_factory=list)
    moves: list[RegMove] = dataclasses.field(default_factory=list)
    restores: list[RegRestore] = dataclasses.field(default_factory=list)

    def __str__(self) -> str:
        return "trgt " + str(self.target) + "[" + ", ".join(str(x) for x in itertools.chain(self.spills, self.restores, self.moves)) + "]"

@dataclasses.dataclass
class BasicBlock:
    il_idx: int
    next_block: BasicBlock | None
    prev_block: BasicBlock | None
    first_statemenent: Statement | None
    last_statement: Statement | None

    # Assigned during Ir.recompute_predecessors
    predecessors: list[BasicBlock] = dataclasses.field(default_factory=list)
    # Assigned during Lsra.do_linear_scan
    active_in: list[CBActiveInterval] = None
    active_out: list[CBActiveInterval] = None

    def outgoing_edges(self) -> Iterable[BlockEdge]:
        # The assumption is that the operands of terminator nodes are block edges
        for operand in self.last_statement.tree.operands:
            assert isinstance(operand, BlockEdge), "operand isn't block edge"

            yield operand

    def tree_execution_order(self) -> Iterable[Tree]:
        statement = self.first_statemenent
        while statement != None:
            for t in statement.tree.tree_execution_order():
                yield t
            statement = statement.next_statement

    def append_tree(self, il_idx: int, tree: Tree) -> None:
        new_statement = Statement(il_idx=il_idx, tree=tree, next_statement=None, prev_statement=self.last_statement)
        if (self.last_statement == None):
            self.last_statement = new_statement
            self.first_statemenent = new_statement
            return
        self.last_statement.next_statement = new_statement
        self.last_statement = new_statement
    
    def __str__(self) -> str:
        return f"blk 0x{hex(self.il_idx)[2:].zfill(4)}"

class BasicBlockList:
    first: BasicBlock
    
    def __init__(self) -> None:
        self.first = BasicBlock(il_idx=0, next_block=None, prev_block=None, first_statemenent=None, last_statement=None)

    def get_or_insert_block_at(self, il_idx: int) -> BasicBlock:
        block = self.first
        while block.il_idx < il_idx:
            if block.next_block == None or block.next_block.il_idx > il_idx:
                break
            block = block.next_block
        
        if block.il_idx == il_idx:
            return block
        
        statement = block.first_statemenent
        while statement.il_idx < il_idx:
            if statement.next_statement == None:
                # il_idx lands past the block

                # insert a new block into the doubly linked list
                new_block = BasicBlock(il_idx=il_idx, next_block=block.next_block, prev_block=block.prev_block, first_statemenent=None, last_statement=None)
                block.next_block = new_block
                if (new_block.next_block != None):
                    new_block.next_block.prev_block = new_block

                return new_block
            statement = statement.next_statement
        
        if statement.il_idx > il_idx:
            # il_idx lands between two statements
            print("panic : il_idx lands between two statements")
            exit(1)
        
        # insert a new block into the doubly linked list
        new_block = BasicBlock(il_idx=il_idx, next_block=block.next_block, prev_block=block.prev_block, first_statemenent=None, last_statement=None)
        block.next_block = new_block
        if (new_block.next_block != None):
            new_block.next_block.prev_block = new_block
        
        new_block.first_statemenent = statement
        new_block.last_statement = block.last_statement

        jmp_statement = Statement(il_idx=0, next_statement=None, prev_statement=block.last_statement.prev_statement, tree=Tree(
            kind=TreeKind.Jmp,
            subtrees=[],
            operands=[BlockEdge(target=new_block)],
            parent=None,
            block=block
        ))
        if (jmp_statement.prev_statement != None):
            jmp_statement.prev_statement.next_statement = jmp_statement
            jmp_statement.il_idx = jmp_statement.prev_statement.il_idx
        else:
            jmp_statement.il_idx = block.il_idx
        if (block.last_statement is block.first_statemenent):
            block.first_statemenent = jmp_statement
        block.last_statement = jmp_statement
        new_block.first_statemenent.prev_statement = None

        return new_block

@dataclasses.dataclass
class Ir:
    blocks: BasicBlockList
    local_vars: int

    ir_idx_count: int = 0

    def recompute_predecessors(self) -> None:
        block = self.blocks.first
        while block != None:
            for edge in block.outgoing_edges():
                edge.target.predecessors.append(block)
            block = block.next_block

    def reindex(self) -> None:
        index = 0

        for tree in self.tree_execution_order():
            tree.ir_idx = index
            index += 1
        
        self.ir_idx_count = index
    
    def block_execution_order(self) -> Iterable[BasicBlock]:
        block = self.blocks.first
        while block != None:
            yield block
            block = block.next_block
    
    def tree_execution_order(self) -> Iterable[Tree]:
        block = self.blocks.first
        while block != None:
            statement = block.first_statemenent
            while statement != None:
                for t in statement.tree.tree_execution_order():
                    yield t
                statement = statement.next_statement
            block = block.next_block

    def dump(self) -> None:
        block = self.blocks.first
        while block != None:
            print(f"blk 0x{hex(block.il_idx)[2:].zfill(4)} - predecessors: [" + ", ".join(str(pred) for pred in block.predecessors) + "]")
            statement = block.first_statemenent
            while statement != None:
                print(f"stmt 0x{hex(statement.il_idx)[2:].zfill(4)}")
                statement.tree.dump()
                statement = statement.next_statement
            block = block.next_block
    
    # Dump into an asm-like representation
    # Note : this code assumes that the only way to obtain a boolean value is by executing cmp and checking the flags.
    # In "real" code, boolean values might be stored in variables as well
    def dump_asm(self) -> None:
        def spill_all(spills: list[RegSpill]) -> None:
            for spill in spills:
                print(f"    mov {spill.interval}, r{spill.reg} ; spill")
        def move_all(moves: list[RegMove]) -> None:
            for move in moves:
                print(f"    mov r{move.reg_to}, r{move.reg_from} ; move")
        def restore_all(restores: list[RegRestore]) -> None:
            for restore in restores:
                print(f"    mov r{restore.reg}, {restore.interval} ; restore")

        for block in self.block_execution_order():
            print(f"IL_{block.il_idx}:")
            for tree in block.tree_execution_order():
                spill_all(tree.spills)
                restore_all(tree.restores)

                match tree.kind:
                    case TreeKind.LdLocal:
                        pass # Handled by spills and restores
                    case TreeKind.StLocal:
                        pass # Handled by spills and restores
                    case TreeKind.Const:
                        print(f"    mov r{tree.reg}, {tree.operands[0]}")
                    case TreeKind.Discard:
                        pass # Do nothing
                    case TreeKind.BinOp:
                        opstr = ""
                        match tree.operands[0]:
                            case Operator.Add:
                                opstr = "add"
                            case Operator.Sub:
                                opstr = "sub"
                            case Operator.Mul:
                                opstr = "mul"
                            case Operator.Div:
                                opstr = "div"
                            case Operator.Eq:
                                opstr = "cmp"

                        print(f"    {opstr} r{tree.reg}, r{tree.subtrees[0].reg}, r{tree.subtrees[1].reg}")
                    case TreeKind.Ret:
                        print(f"    mov rret, r{tree.subtrees[0].reg}")
                    case TreeKind.Branch:
                        if_name = f"IF_EDGE_IL_{block.il_idx}_IL_{tree.operands[0].target.il_idx}"
                        else_name = f"ELSE_EDGE_IL_{block.il_idx}_IL_{tree.operands[1].target.il_idx}"

                        print(f"    jz r{tree.subtrees[0].reg} {else_name}")
                        print(f"    jnz r{tree.subtrees[0].reg} {if_name}")

                        # If edge
                        print(if_name + ":")
                        spill_all(tree.operands[0].spills)
                        move_all(tree.operands[0].moves)
                        restore_all(tree.operands[0].restores)
                        print(f"    jmp IL_{tree.operands[0].target.il_idx}")

                        # Else edge
                        print(else_name + ":")
                        spill_all(tree.operands[1].spills)
                        move_all(tree.operands[1].moves)
                        restore_all(tree.operands[1].restores)
                        print(f"    jmp IL_{tree.operands[1].target.il_idx}")
                    case TreeKind.Jmp:
                        name = f"JMP_EDGE_IL_{block.il_idx}_IL_{tree.operands[0].target.il_idx}"
                        
                        print(name + ":")
                        spill_all(tree.operands[0].spills)
                        move_all(tree.operands[0].moves)
                        restore_all(tree.operands[0].restores)
                        print(f"    jmp IL_{tree.operands[0].target.il_idx}")
                    
                        