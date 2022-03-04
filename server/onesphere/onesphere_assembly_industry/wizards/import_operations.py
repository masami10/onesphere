# -*- coding: utf-8 -*-

from odoo import models, fields, api
import xlrd, base64
from odoo.exceptions import UserError, ValidationError
from odoo.tools import ustr
from odoo.addons.onesphere_assembly_industry.constants import ALL_TIGHTENING_TEST_TYPE_LIST
import os
import logging
import binascii
import pyexcel

_logger = logging.getLogger(__name__)

FIRST_DATA_ROW = 3

COLUMN_STEP_TYPE = 5
COLUMN_OPERATION_CODE = 1
COLUMN_WORKCENTER_CODE = 2
COLUMN_STEP_CODE = 4
COLUMN_PRODUCT_CODE = 6
COLUMN_STEP_NOTE = 7
COLUMN_TOOL_SN_STR = 9
COLUMN_SCREW_CODE = 11
COLUMN_TIGHTENING_PSET = 12
COLUMN_TiGHTENING_IMG = 8
COLUMN_TIGHTENING_POINT_NAME = 10

class ImportOperation(models.TransientModel):
    _name = 'onesphere.import.operation'
    _description = 'Import Operation'
    _inherit = ['onesphere.import.mixin']

    def _create_operation(self, data):
        operation_code = data.cell_value(FIRST_DATA_ROW, COLUMN_OPERATION_CODE)
        workcenter_code = data.cell_value(FIRST_DATA_ROW, COLUMN_WORKCENTER_CODE)
        workcenter = self.env['mrp.workcenter'].search([('code', '=', workcenter_code)])
        if not workcenter:
            raise ValidationError(f'Can Not Found Workcenter,Code{workcenter_code}')
        operation_data = {
            'name': operation_code,
            'workcenter_id': workcenter.id,
        }
        operation = self.env['mrp.routing.workcenter'].create(operation_data)
        return operation

    def _create_step(self, operation, step_data, step_seq):
        step_code = step_data[COLUMN_STEP_CODE]
        step_type = step_data[COLUMN_STEP_TYPE]
        product_code = step_data[COLUMN_PRODUCT_CODE]
        step_note = step_data[COLUMN_STEP_NOTE]
        tightening_img = step_data[COLUMN_TiGHTENING_IMG]
        if not product_code:
            product_id = False
        else:
            product = self.env['product.product'].search([('default_code', '=', product_code)])
            if not product:
                raise ValidationError(f'Invalid Product Code:{product_code}!')
            product_id = product.id
        test_type_id = self.env['oneshare.quality.point.test_type'].search(
            [('technical_name', '=', step_type)]).id
        if not test_type_id:
            raise ValidationError(f'Invalid Step Type:{step_type}!')
        step_dic = {
            'code': step_code,
            'test_type_id': test_type_id,
            'component_id': product_id,
            'note': step_note,
        }
        if step_type in ALL_TIGHTENING_TEST_TYPE_LIST and tightening_img:
            img_url = self.img_url + '\\' + tightening_img
            with open(img_url, "rb") as f:
                img_bin = base64.b64encode(f.read())
            step_dic.update({'worksheet_img': img_bin})
        step = self.env['oneshare.quality.point'].create(step_dic)

        operation_step_rel_dic = {
            'operation_id': operation.id,
            'work_step_id': step.id,
            'sequence': step_seq,
        }
        self.env['onesphere.mrp.operation.step.rel'].create(operation_step_rel_dic)
        return step

    def _create_tightening_point(self, step_data, step, tightening_points_seq):
        if not step:
            raise ValidationError('No step to add tightening points!')
        tool_group_ids = []
        tool_sn_str = ustr(step_data[COLUMN_TOOL_SN_STR])
        screw_code = step_data[COLUMN_SCREW_CODE]
        tightening_pset = step_data[COLUMN_TIGHTENING_PSET]
        tightening_point_name = step_data[COLUMN_TIGHTENING_POINT_NAME]
        tool_sn_list = tool_sn_str.split(',')
        for tool_sn in tool_sn_list:
            tool = self.env['maintenance.equipment'].search([('serial_no', '=', tool_sn)])
            if not tool:
                raise ValidationError(f'Can not found tool,serial_no:{tool_sn}')
            tool_group_id = self.env['mrp.workcenter.group.tightening.tool'].search(
                [('tightening_tool_id', '=', tool.id)]).id
            tool_group_ids.append(tool_group_id)

        screw_model = self.env['product.product']
        screw = screw_model.search([('default_code', '=', screw_code)])
        if not screw:
            screw_dic = {
                'name': screw_code,
                'default_code': screw_code,
                'type': 'consu',
            }
            screw = screw_model.create(screw_dic)

        point_dic = {
            'name': tightening_point_name,
            'tightening_tool_ids': [(6, 0, tool_group_ids)],
            'product_id': screw.id,
            'tightening_pet': tightening_pset,
            'parent_quality_point_id': step.id,
            'sequence': tightening_points_seq,
        }
        self.env['onesphere.tightening.opr.point'].create(point_dic)

    def _import_operation(self, operation_data):
        operation = self._create_operation(operation_data)
        step_seq = 0
        need_add_points_step = False
        tightening_points_seq = 1
        for i in range(FIRST_DATA_ROW, len(operation_data)):
            row_data = [content for content in operation_data[i] if content != '']
            if len(row_data) < 1:
                continue
            step_data = operation_data[i]
            step_type = step_data[COLUMN_STEP_TYPE]
            if not step_type:
                self._create_tightening_point(step_data, need_add_points_step, tightening_points_seq)
                tightening_points_seq += 1
                continue
            if step_type in ALL_TIGHTENING_TEST_TYPE_LIST:
                step = self._create_step(operation, step_data, step_seq)
                need_add_points_step = step
                self._create_tightening_point(step_data, need_add_points_step, tightening_points_seq)
                tightening_points_seq += 1
            else:
                self._create_step(operation, step_data, step_seq)
            step_seq += 1

    def button_import_operations(self):
        if not self.file_type:
            raise ValidationError('Please Select A File Type!')
        file_content = binascii.a2b_base64(self.file)
        book = pyexcel.get_book(file_type=self.file_type, file_content=file_content)
        for sheet in book:
            if len(sheet) <= FIRST_DATA_ROW:
                continue
            operation_code = sheet.cell_value(FIRST_DATA_ROW, COLUMN_OPERATION_CODE)
            try:
                self._import_operation(sheet)
                self.env.user.notify_success(f'Create Operation Success,Operation Code:{operation_code}')
            except Exception as e:
                _logger.error(f'Create Operation Failed,Reason:{ustr(e)}')
                self.env.user.notify_warning(f'Create Operation Failed,Operation Code:{operation_code}')
