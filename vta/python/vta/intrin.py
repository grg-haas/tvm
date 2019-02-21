"""VTA related intrinsics"""
from __future__ import absolute_import as _abs

import tvm

def gemm(env, mock=False):
    """Matrix-matrix multiply intrinsic

    Parameters
    ----------
    env : Environment
        The Environment

    mock : bool
        Whether create a mock version.
    """
    wgt_lanes = env.WGT_ELEM_BITS // env.WGT_WIDTH
    assert wgt_lanes == env.BLOCK_OUT * env.BLOCK_IN
    wgt_shape = (env.BLOCK_OUT, env.BLOCK_IN)
    assert wgt_shape[0] * wgt_shape[1] == wgt_lanes

    inp_lanes = env.INP_ELEM_BITS // env.INP_WIDTH
    assert inp_lanes == env.BATCH * env.BLOCK_IN
    inp_shape = (env.BATCH, env.BLOCK_IN)
    assert inp_shape[0] * inp_shape[1] == inp_lanes

    out_lanes = env.ACC_ELEM_BITS // env.ACC_WIDTH
    assert out_lanes == env.BATCH * env.BLOCK_OUT
    out_shape = (env.BATCH, env.BLOCK_OUT)
    assert out_shape[0] * out_shape[1] == out_lanes

    wgt = tvm.placeholder((wgt_shape[0], wgt_shape[1]),
                          dtype="int%d" % env.WGT_WIDTH,
                          name=env.wgt_scope)
    inp = tvm.placeholder((inp_shape[0], inp_shape[1]),
                          dtype="int%d" % env.INP_WIDTH,
                          name=env.inp_scope)
    k = tvm.reduce_axis((0, wgt_shape[1]), name="k")
    out_dtype = "int%d" % env.ACC_WIDTH
    out = tvm.compute((out_shape[0], out_shape[1]),
                      lambda i, j: tvm.sum(inp[i, k].astype(out_dtype) *
                                           wgt[j, k].astype(out_dtype),
                                           axis=[k]),
                      name="out")
    wgt_layout = tvm.decl_buffer(
        wgt.shape, wgt.dtype, env.wgt_scope,
        scope=env.wgt_scope, offset_factor=wgt_lanes, data_alignment=wgt_lanes)
    inp_layout = tvm.decl_buffer(
        inp.shape, inp.dtype, env.inp_scope,
        scope=env.inp_scope, offset_factor=inp_lanes, data_alignment=inp_lanes)
    out_layout = tvm.decl_buffer(
        out.shape, out.dtype, env.acc_scope,
        scope=env.acc_scope, offset_factor=out_lanes, data_alignment=out_lanes)

    def intrin_func(ins, outs):
        """Matrix-matrix multiply intrinsic function"""
        dinp, dwgt = ins
        dout = outs[0]
        def instr(index):
            """Generate matrix-matrix multiply VTA instruction"""
            irb = tvm.ir_builder.create()
            dev = env.dev
            irb.scope_attr(dev.vta_axis, "coproc_scope",
                           dev.get_task_qid(dev.QID_COMPUTE))
            irb.scope_attr(dev.vta_axis, "coproc_uop_scope",
                           dev.vta_push_uop)
            if index in (0, 2):
                irb.emit(tvm.call_extern(
                    "int32", "VTAUopPush",
                    0, 0,
                    dout.access_ptr("rw", "int32"),
                    dinp.access_ptr("r", "int32"),
                    dwgt.access_ptr("r", "int32"),
                    0, 0, 0))
            else:
                irb.emit(tvm.call_extern(
                    "int32", "VTAUopPush",
                    0, 1,
                    dout.access_ptr("rw", "int32"),
                    0,
                    0,
                    0, 0, 0))
            return irb.get()
        # return a triple of normal-set, reset, update
        nop = tvm.make.Evaluate(0)
        if mock:
            return (nop, nop, nop)
        return (instr(0), instr(1), instr(2))

    return tvm.decl_tensor_intrin(out.op, intrin_func,
                                  name="GEMM",
                                  binds={inp: inp_layout,
                                         wgt: wgt_layout,
                                         out: out_layout})
