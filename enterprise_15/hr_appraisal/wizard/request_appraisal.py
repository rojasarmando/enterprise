# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError
from odoo.tools import html_sanitize, is_html_empty

_logger = logging.getLogger(__name__)


class RequestAppraisal(models.TransientModel):
    _name = 'request.appraisal'
    _inherit = 'mail.composer.mixin'
    _description = "Request an Appraisal"

    @api.model
    def default_get(self, fields):
        if not self.env.user.email:
            raise UserError(_("Unable to post message, please configure the sender's email address."))
        result = super(RequestAppraisal, self).default_get(fields)
        if not set(fields) & set(['employee_id', 'template_id', 'recipient_ids']):
            return result
        if self.env.context.get('default_appraisal_id'):
            appraisal = self.env['hr.appraisal'].browse(self.env.context['default_appraisal_id'])
            employee = appraisal.employee_id
            managers = appraisal.manager_ids
            if self.env.user.employee_id in managers:
                template = self.env.ref('hr_appraisal.mail_template_appraisal_request', raise_if_not_found=False)
                recipients = self._get_recipients(employee)
            elif employee.user_id == self.env.user:
                template = self.env.ref('hr_appraisal.mail_template_appraisal_request_from_employee', raise_if_not_found=False)
                recipients = self._get_recipients(managers)
            else:
                template = self.env.ref('hr_appraisal.mail_template_appraisal_request', raise_if_not_found=False)
                recipients = self._get_recipients(employee | managers)

            result.update({
                'template_id': template.id,
                'recipient_ids': recipients.ids,
                'employee_id': employee.id,
                'appraisal_id': appraisal.id,
            })
        return result

    @api.model
    def _get_recipients(self, employees):
        partners = self.env['res.partner']
        employees_with_user = employees.filtered('user_id')

        for employee in employees_with_user:
            partners |= employee.user_id.partner_id

        for employee in employees - employees_with_user:
            employee_work_email = tools.email_normalize(employee.work_email)
            if employee_work_email:
                name_email = tools.formataddr((employee.name, employee_work_email))
                partners |= self.env['res.partner'].sudo().find_or_create(name_email)
        return partners

    appraisal_id = fields.Many2one('hr.appraisal', required=True)
    user_body = fields.Html('User Contents')
    email_from = fields.Char(
        'From', required=True,
        default=lambda self: self.env.user.email_formatted,
        help="Email address of the sender",
    )
    author_id = fields.Many2one(
        'res.partner', 'Author', required=True,
        default=lambda self: self.env.user.partner_id.id,
        help="Author of the message.",
    )
    employee_id = fields.Many2one('hr.employee', 'Appraisal Employee')
    recipient_ids = fields.Many2many('res.partner', string='Recipients', required=True)

    @api.depends('employee_id')
    def _compute_subject(self):
        for wizard in self.filtered('employee_id'):
            if wizard.template_id:
                wizard.subject = self.sudo()._render_template(wizard.template_id.subject, 'res.users', self.env.user.ids, post_process=True)[self.env.user.id]

    @api.depends('template_id', 'recipient_ids')
    def _compute_body(self):
        for wizard in self:
            user_body = wizard.user_body
            user_body = user_body if not is_html_empty(html_sanitize(user_body, strip_style=True, strip_classes=True)) else False
            if wizard.template_id:
                ctx = {
                    'employee_to_name': ', '.join(wizard.recipient_ids.sorted('name').mapped('name')),
                    'author_name': wizard.author_id.name,
                    'author_mail': wizard.author_id.email,
                    'recipient_users': wizard.recipient_ids.mapped('user_ids'),
                    'url': "ctx['url']",
                    'user_body': user_body
                }
                wizard.body = self.with_context(ctx).sudo()._render_template(wizard.template_id.body_html, 'res.users', self.env.user.ids, post_process=False, engine='qweb')[self.env.user.id]
            elif not wizard.body:
                wizard.body = ''

    def _compute_can_edit_body(self):
        for record in self:
            # Do not bypass verification (as the template is rendered 2 times with 2 different models)
            record.can_edit_body = True

    # Overrides of mail.composer.mixin
    @api.depends('subject')  # fake trigger otherwise not computed in new mode
    def _compute_render_model(self):
        self.render_model = 'hr.appraisal'

    def action_invite(self):
        """ Process the wizard content and proceed with sending the related
            email(s), rendering any template patterns on the fly if needed """
        self.ensure_one()
        appraisal = self.appraisal_id
        appraisal.message_subscribe(partner_ids=self.recipient_ids.ids)

        ctx = {
            'url': '/mail/view?model=%s&res_id=%s' % ('hr.appraisal', appraisal.id),
        }
        context_self = self.with_context(ctx)
        subject = context_self._render_field('subject', appraisal.ids, post_process=False)[appraisal.id]
        # hack to prepare the rendering of the body for ctx
        context_self.body = context_self.body.replace('href', 't-att-href')
        body = context_self._render_field('body', appraisal.ids, engine='qweb', post_process=True)[appraisal.id]

        appraisal.message_post(
            subject=subject,
            body=body,
            message_type='comment',
            email_from=self.author_id.email,
            email_layout_xmlid='mail.mail_notification_light',
            partner_ids=self.recipient_ids.ids)

        return {
            'view_mode': 'form',
            'res_model': 'hr.appraisal',
            'type': 'ir.actions.act_window',
            'target': 'current',
            'res_id': appraisal.id,
        }
