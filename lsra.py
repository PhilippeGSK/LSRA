from __future__ import annotations
import dataclasses
from ir import *
import ir as irepr

# Represents a register
@dataclasses.dataclass
class Register:
    active_interval: Interval | None

# These will be attached to signify an interval should be spilled from a register
@dataclasses.dataclass
class RegSpill:
    reg: int
    interval: Interval

    def __str__(self) -> str:
        return f"spill {self.interval} from r{self.reg}"

# These will be attached to signify an interval should be restored into a register
@dataclasses.dataclass
class RegRestore:
    reg: int
    interval: Interval
    
    def __str__(self) -> str:
        return f"restore {self.interval} into r{self.reg}"

# These will be attached to signify an interval should be moved from one register to another (for example during active in / out set resolution)
@dataclasses.dataclass
class RegMove:
    reg_from: int
    reg_to: int
    interval: Interval
    
    def __str__(self) -> str:
        return f"move {self.interval} from r{self.reg_from} to r{self.reg_to}"

# Represents the live range of an interval
@dataclasses.dataclass
class LiveRange:
    first_write_at: int
    last_read_at: int

# Represents a use position of an interval
@dataclasses.dataclass
class UsePos:
    belongs_to: Interval
    used_in: Tree
    on_block_boundary: bool

# Represents a write position of an interval
@dataclasses.dataclass
class WritePos:
    belongs_to: Interval
    used_in: Tree
    on_block_boundary: bool

# Cross boundary active interval. Those are going to be stored in the active_in / active_out sets of blocks
@dataclasses.dataclass
class CBActiveInterval:
    reg: int
    interval: Interval

# Represents a value (local var or tree temp)
@dataclasses.dataclass
class Interval:
    of: int | Tree
    use_positions: list[UsePos]
    write_positions: list[WritePos]
    live_range: LiveRange
    live_in: int | None

    def __str__(self):
        if isinstance(self.of, int):
            return f"local {self.of}"
        else:
            return f"tree tmp {self.of.ir_idx}"
        
    def first_use_pos(self, current_pos: int) -> UsePos | None:
        for use_pos in self.use_positions:
            if use_pos.used_in.ir_idx < current_pos:
                continue

            return use_pos

    def first_write_pos(self, current_pos: int) -> WritePos | None:
        for write_pos in self.write_positions:
            if write_pos.used_in.ir_idx < current_pos:
                continue
            
            return write_pos

# The main class that performs LSRA
class Lsra:
    registers: list[Register]
    var_intervals: list[Interval]
    tree_intervals: list[Interval]
    active_intervals: list[Interval]
    current_block: BasicBlock
    current_tree: Tree
    
    # Whether or not we ourselves to free the intervals that are about to be read so that we can reuse the registers for operands
    # and output
    # Also see related comment on try_allocate_with_free_reg
    allow_operand_reuse: bool

    def __init__(self, num_regs: int = 4, allow_operand_reuse: bool = True) -> None:
        self.registers = []
        for _ in range(num_regs):
            self.registers.append(Register(active_interval=None))
        self.allow_operand_reuse = allow_operand_reuse
        self.var_intervals = []
        self.tree_intervals = []
        self.active_intervals = []
        self.current_block = None
        self.current_tree = None
    
    # Removes expired intervals from the active_intervals list and frees the corresponding registers
    def free_intervals(self) -> None:
        pos = self.current_tree.ir_idx
        new_active_intervals = []
        for active_interval in self.active_intervals:
            last_use_reached = active_interval.live_range.last_read_at < pos
            
            if not last_use_reached and self.allow_operand_reuse:
                # If we allow operand reuse, we free operand registers for the output
                # Disallow "reusing operands" on block boundaries because variables used on boundary
                # TODO : this needs improvement
                first_use_pos = active_interval.first_use_pos(pos)
                if first_use_pos != None and not first_use_pos.on_block_boundary:
                    last_use_reached = active_interval.live_range.last_read_at == pos
            
            if not last_use_reached:
                # First use pos could be None for a variable that is expected to live further than its last actual use pos (LdLocal case)
                first_use_pos = active_interval.first_use_pos(pos)
                first_write_pos = active_interval.first_write_pos(pos)

                if first_use_pos != None and first_write_pos != None and first_use_pos.used_in.block is self.current_block:
                    # Interval will be remade active by a write later in this same block
                    last_use_reached = first_write_pos.used_in.ir_idx < first_use_pos.used_in.ir_idx

                    # If we allow operand reuse, we free operand registers for the output
                    # Disallow "reusing operands" on block boundaries because variables used on boundary
                    # TODO : this needs improvement
                    if not last_use_reached and self.allow_operand_reuse and not first_write_pos.on_block_boundary:
                        last_use_reached = first_write_pos.used_in.ir_idx == first_use_pos.used_in.ir_idx

            if not last_use_reached:
                new_active_intervals.append(active_interval)
                continue
            
            reg: Register = self.registers[active_interval.live_in]
            reg.active_interval = None
            active_interval.live_in = None
        self.active_intervals = new_active_intervals
    
    # Tries to make an interval active without spilling
    # If possible, we'd like to reuse the register of one of the operands (only useful when we have allow_operand_reuse)
    # The reason is because we'd rather emit, in the future, the following :
    # `add r2, r1`
    # which reuses r2 as both the operand and result register
    # instead of the following
    # `mov r0, r2`
    # `add r2, r1`
    # just because r0 was free
    def try_activate_with_free_reg(self, inter: Interval) -> bool:
        best_reg_i = -1
        best_reg: Register | None = None

        for reg_i, reg in enumerate(self.registers):
            if reg.active_interval == None:
                if best_reg == None:
                    best_reg = reg
                    best_reg_i = reg_i
                else:
                    # Check if the reg is already one of the operands. If yes, that'll be the best reg we can find
                    done_searching = False
                    for subtree in inter.first_use_pos(self.current_tree.ir_idx).used_in.subtrees:
                        if subtree.reg == reg_i:
                            best_reg = reg
                            best_reg_i = best_reg_i
                            done_searching = True
                            break
                    if done_searching:
                        break

        if best_reg == None:
            return False

        # If the current tree isn't the one that writes the value or if it doesn't already restore the value, 
        # we need to add a restore.
        if self.current_tree is not inter.of:
            if not any(restore.interval == inter for restore in self.current_tree.restores):
                self.current_tree.restores.append(RegRestore(reg=best_reg_i, interval=inter))
        inter.live_in = best_reg_i
        best_reg.active_interval = inter
        self.active_intervals.append(inter)
        return True
    
    # Spills an interval and returns the freed register
    def spill_interval(self, inter: Interval) -> int:
        assert inter.live_in != None, "trying to spill an interval that's not active"

        # We could try looking for a better spot to spill the interval in
        # (eg. if we're in a loop and the interval isn't going to be used inside, we should spill the interval outside the loop)
        self.current_tree.spills.append(RegSpill(inter.live_in, inter))
        # Register will be decided at the time of restoration
        # For variable intervals, restores will be inserted at the time of use
        if not isinstance(inter.of, int):
            use_pos = inter.first_use_pos(self.current_tree.ir_idx)
            use_pos.used_in.restores.append(RegRestore(-1, inter))

        res = inter.live_in
        inter.live_in = None
        self.active_intervals.remove(inter)
        self.registers[res].active_interval = None

        return res
    
    # Ensures an interval is active
    def activate_interval(self, inter: Interval) -> None:
        if (inter.live_in != None):
            # Interval is already active
            return
        
        # If we can, we should use a free register
        if (self.try_activate_with_free_reg(inter)):
            return
        
        # We couldn't find a free register, we need to spill one
        # Find the best candiate to spill
        # The heuristic used here is to pick the one which will have to be restored the furthest in the future
        current_pos = self.current_tree.ir_idx
        inter_use_pos = inter.first_use_pos(current_pos)    
        # This shouldn't happen because we shouldn't activate intervals that aren't going to be used anymore
        assert inter_use_pos != None
        best_interval: Interval | None = None
        best_use_pos: UsePos | None = None
        for active_interval in self.active_intervals:
            use_pos = active_interval.first_use_pos(current_pos)

            # This shouldn't happen in general because active intervals should have use positions in the future
            # We called free_intervals() to ensure that
            # TODO : after liveness analysis is done, the use_pos == None check should become
            # `assert use_pos != None, "None use pos"`
            if use_pos == None:
                best_interval = active_interval
                best_use_pos = use_pos
                break
            
            # We can't spill an interval we're about to use
            if use_pos.used_in.ir_idx <= inter_use_pos.used_in.ir_idx:
                continue

            if best_interval == None or use_pos.used_in.ir_idx > best_use_pos.used_in.ir_idx:
                best_interval = active_interval
                best_use_pos = use_pos

        if best_interval == None:
            print ("regs")
            for reg in self.registers:
                print("    " + str(reg.active_interval))
            print("active")
            for active_interval in self.active_intervals:
                print("    " + str(active_interval))
            raise Exception("No intervals elligible for spilling at " + str(self.current_tree.ir_idx))
        
        reg = self.spill_interval(best_interval)

        inter.live_in = reg
        self.registers[inter.live_in].active_interval = inter
        self.active_intervals.append(inter)

    # Performs LSRA on the provided ir.
    # Should be called on a freshly initialized instance of Lsra.
    # Block predecessors in the ir should have been filled in (by Ir.recompute_predecessors)
    # Trees in the ir should be indexed in execution order (ir_idx filled in by Ir.reindex)
    def do_linear_scan(self, ir: Ir) -> None:
        # Initialize the var intervals
        self.var_intervals = []
        for i in range(ir.local_vars):
            self.var_intervals.append(Interval(
                of=i, 
                use_positions=[],
                write_positions=[],
                live_range=LiveRange(first_write_at=ir.ir_idx_count, last_read_at=-1), 
                live_in=None
            ))

        # Find the last read, first read, and first write as well as the use positions of every local variable
        for block in ir.block_execution_order():
            for tree in block.tree_execution_order():
                if tree.kind == irepr.TreeKind.StLocal:
                    inter: Interval = self.var_intervals[tree.operands[0]]
                    loc = tree.ir_idx
                    if loc < inter.live_range.first_write_at:
                        inter.live_range.first_write_at = loc
                    inter.write_positions.append(WritePos(belongs_to=inter, used_in=tree, on_block_boundary=False))
                if tree.kind == irepr.TreeKind.LdLocal:
                    inter: Interval = self.var_intervals[tree.operands[0]]
                    # The value is going to be last read in the parent of the LdLocal node
                    loc = tree.parent.ir_idx
                    if loc > inter.live_range.last_read_at:
                        inter.live_range.last_read_at = loc
                    inter.use_positions.append(UsePos(belongs_to=inter, used_in=tree, on_block_boundary=False))
            
            # TODO : liveness analysis should compute when will be the last time we could jump back to a previous block that uses a variable
            for var_interval in self.var_intervals:
                var_interval.live_range.last_read_at = ir.ir_idx_count

        # Linear scan
        for block in ir.block_execution_order():
            self.current_block = block

            # Select active in set amongst predecessors. The block execution order should guarantee that if there are predecessors,
            # At least one has an active_out set

            # If we don't have predecessors (eg. first block) we start fresh without any active interval
            # If only the first block is without predecessors, this is redundant with the previous initialization
            # All other predecessor-less block should be eliminated in a previous phase as they're unreachable
            # TODO : ensure this
            for reg in self.registers:
                reg.active_interval = None
            for interval in self.active_intervals:
                interval.live_in = None
            self.active_intervals = []

            if block.predecessors != []:
                active_in = None

                # TODO : we should select the active_out set better (considering edge weights and such)
                for predecessor in block.predecessors:
                    if predecessor.active_out != None:
                        active_in = predecessor.active_out
                        break
                
                assert active_in != None, "no predecessor with active_out set"

                for active in active_in:
                    self.registers[active.reg].active_interval = active.interval
                    active.interval.live_in = active.reg
                    self.active_intervals.append(active.interval)
                
                # Fill in the active_in set for the block
                block.active_in = active_in

            for tree in block.tree_execution_order():
                self.current_tree = tree

                # Restores aren't allowed to reuse operand registers
                allow_operand_reuse = self.allow_operand_reuse
                self.allow_operand_reuse = False
                self.free_intervals()

                # If the tree spills or restores intervals, we update the active interval set accordingly
                # The spill part might never be encountered, but it's implemented for the sake of completeness
                for spill in tree.spills:
                    assert spill.interval.live_in != None, "spill of interval that's not active"
                    assert spill.reg == spill.interval.live_in, "spill register and register of interval to spill don't match"
                    
                    self.active_intervals.remove(spill.interval)
                    self.registers[spill.reg].active_interval = None
                    spill.interval.live_in = None
                for restore in tree.restores:
                    assert restore.interval.live_in == None, "finding a restore reg for an interval that's already active"
                    
                    self.activate_interval(restore.interval)
                    restore.reg = restore.interval.live_in
                
                # Free intervals again, this time restoring allow_operand_reuse, so that output from trees can reuse operand registers
                self.allow_operand_reuse = allow_operand_reuse
                if allow_operand_reuse:
                    self.free_intervals()

                # Special case for LdLocal : when we use the value of a var interval, we need to activate its interval.
                if tree.kind == irepr.TreeKind.LdLocal:
                    inter: Interval = self.var_intervals[tree.operands[0]]
                    self.activate_interval(inter)
                    tree.reg = inter.live_in
                
                # Special case for StLocal : when we write to a local variable,
                # we can just say its interval becomes active in the ouput register of the child node
                # actual writes to memory will be taken care of later when spilling that interval
                # If the local variable was already active, we can just free the register it was in.
                # This is ok to do because there is no control flow within a block. Syncing up variables to be in the registers
                # they're expected to be in is done during block boundary processing
                elif tree.kind == irepr.TreeKind.StLocal:
                    inter: Interval = self.var_intervals[tree.operands[0]]

                    # If the interval already lives in that register, nothing to do
                    if tree.subtrees[0].reg != inter.live_in:
                        # If we're trying to store into a register that *another* variable lives in, we spill it.
                        # Otherwise, it's just a tree temp, so we can discard it
                        # TODO : try to simply move it to another register
                        if self.registers[tree.subtrees[0].reg].active_interval != None and isinstance(self.registers[tree.subtrees[0].reg].active_interval.of, int):
                            self.spill_interval(self.registers[tree.subtrees[0].reg].active_interval)
                        else:
                            if self.registers[tree.subtrees[0].reg].active_interval != None:
                                self.active_intervals.remove(self.registers[tree.subtrees[0].reg].active_interval)

                        if inter.live_in != None:
                            # If the variable previously lived in another register, clear it
                            print(inter.live_in)
                            self.registers[inter.live_in].active_interval = None
                        else:
                            # If the interval wasn't alive, it is now
                            self.active_intervals.append(inter)

                        inter.live_in = tree.subtrees[0].reg
                        self.registers[inter.live_in].active_interval = inter

                    # Since tree.reg is only meant to represent output registers,
                    # we're instead storing the used register as an operand.
                    # TODO : clarify this in Ir.dump
                    # It is unclear if this is needed at all
                    tree.operands.append(inter.live_in)
                
                # In all other case : create an interval for the current tree if it produces a value
                elif tree.parent != None:
                    tree_interval = Interval(
                        of=tree,
                        write_positions=[],
                        use_positions=[], 
                        live_range=LiveRange(first_write_at=tree.ir_idx, last_read_at=tree.parent.ir_idx), 
                        live_in=None
                    )
                    tree_interval.write_positions.append(WritePos(belongs_to=tree_interval, used_in=tree, on_block_boundary=False))
                    tree_interval.use_positions.append(UsePos(belongs_to=tree_interval, used_in=tree.parent, on_block_boundary=False))
                    self.activate_interval(tree_interval)
                    tree.reg = tree_interval.live_in

            # Remove leftover tree temps in case they're still there because they were used on the terminator and we didn't allow for operand
            # reuse
            new_active_intervals = []
            for active_interval in self.active_intervals:
                if not isinstance(active_interval.of, int):
                    self.registers[active_interval.live_in].active_interval = None
                    active_interval.live_in = None
                else:
                    new_active_intervals.append(active_interval)
            self.active_intervals = new_active_intervals

            # Fill out the active_out set for the block
            active_out = []
            for active_interval in self.active_intervals:
                assert isinstance(active_interval.of, int), "active tree temp encountered after block ended"

                active_out.append(CBActiveInterval(reg=active_interval.live_in, interval=active_interval))

            block.active_out = active_out
        
        # Conflict resolution between active in / out sets
        for block in ir.block_execution_order():
            for edge in block.outgoing_edges():
                # Add spills for variables that aren't active in the next block
                for active_out in block.active_out:
                    if not any(active_in.interval.of == active_out.interval.of for active_in in edge.target.active_in):
                        edge.spills.append(RegSpill(reg=active_out.reg, interval=active_out.interval))

                # Move variables that are active in the next block but in different registers
                for active_out in block.active_out:
                    for active_in in edge.target.active_in:
                        if active_out.interval.of == active_in.interval.of and active_out.reg != active_in.reg:
                            print(active_out.interval.of)
                            edge.moves.append(RegMove(reg_from=active_out.reg, reg_to=active_in.reg, interval=active_out.interval))
                
                # Restore variables that are active in the next block but weren't in the previous
                for active_in in edge.target.active_in:
                    if not any(active_out.interval.of == active_in.interval.of for active_out in block.active_out):
                        print(active_in.interval.of)
                        edge.restores.append(RegRestore(reg=active_in.reg, interval=active_in.interval))
                


