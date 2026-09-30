from django.test import TestCase

from contacts.models import Contact
from contacts.serializers import ContactSerializer
from contacts.utils import (
    company_from_email,
    company_from_signature,
    format_company,
    is_internal_email,
    phone_from_signature,
    upsert_contact_from_email,
)

SIGNATURE = """
<div>
  <p>Buongiorno,<br>in allegato la nostra offerta.</p>
  <div><br></div>
  <div>Andrea Kiss</div>
  <div>Co.Ri.Metal S.R.L.</div>
  <div>10092 Beinasco (Torino) - Italy</div>
  <div>Tel +39 011 3983511</div>
  <div>Mobile +39 331 4037568</div>
  <div>&lt;commerxxxx.ricambixxxx@corimetal.it&gt;</div>
</div>
"""

# A supplier signature, the shape most of them actually send.
SUPPLIER_SIGNATURE = """
<div>
  <p>Gentile,</p>
  <p>la nostra offerta è in allegato.</p>
  <div><br></div>
  <div>Marilyn Colon</div>
  <div>Opti Manufacturing Inc.</div>
  <div>440 Industrial Park Road, Building 7</div>
  <div>Houston TX 77002</div>
  <div>Tel: +1 713 555 0142</div>
  <div>Mobile: +1 713 555 0199</div>
  <div><a href="https://www.optimanufacturing.com">optimanufacturing.com</a></div>
</div>
"""


class CompanyFromEmailTests(TestCase):
    def test_takes_the_domain_without_its_suffix(self):
        self.assertEqual(company_from_email('luigi@rossimax.it'), 'rossimax')
        self.assertEqual(company_from_email('info@rossimax.com'), 'rossimax')

    def test_strips_subdomains_and_www(self):
        self.assertEqual(company_from_email('sales@mail.rossimax.it'), 'rossimax')
        self.assertEqual(company_from_email('luigi@www.rossimax.it'), 'rossimax')

    def test_country_code_suffix_keeps_the_company(self):
        self.assertEqual(company_from_email('luigi@rossimax.co.uk'), 'rossimax')

    def test_address_without_a_domain_gives_nothing(self):
        self.assertEqual(company_from_email('luigi'), '')
        self.assertEqual(company_from_email(''), '')


class FormatCompanyTests(TestCase):
    def test_a_short_acronym_is_uppercased(self):
        self.assertEqual(format_company('dhl'), 'DHL')
        self.assertEqual(format_company('knf'), 'KNF')

    def test_a_longer_domain_is_capitalised(self):
        self.assertEqual(format_company('rossimax'), 'Rossimax')
        self.assertEqual(format_company('optimanufacturing'), 'Optimanufacturing')

    def test_a_name_that_already_has_capitals_is_left_alone(self):
        self.assertEqual(format_company('rossiMax'), 'rossiMax')
        self.assertEqual(format_company('RossiMax Italia S.r.l.'), 'RossiMax Italia S.r.l.')

    def test_nothing_in_nothing_out(self):
        self.assertEqual(format_company(''), '')
        self.assertEqual(format_company('   '), '')


class CompanyFromSignatureTests(TestCase):
    def test_the_company_line_wins_over_the_person_and_the_address(self):
        self.assertEqual(
            company_from_signature(SUPPLIER_SIGNATURE, 'Marilyn Colon'),
            'Opti Manufacturing Inc.',
        )

    def test_an_italian_signature_works_too(self):
        self.assertEqual(
            company_from_signature(SIGNATURE, 'Andrea Kiss'),
            'Co.Ri.Metal S.R.L.',
        )

    def test_a_closing_is_not_a_company(self):
        self.assertEqual(
            company_from_signature(
                '<p>Buongiorno,<br>Luigi Rossi<br>Best regards,<br>'
                'Rossimax Italia S.r.l.<br>Via Roma 12, 20100 Milano</p>',
                'Luigi Rossi',
            ),
            'Rossimax Italia S.r.l.',
        )

    def test_a_legal_form_on_its_own_is_not_a_company(self):
        self.assertEqual(
            company_from_signature('<p>Luigi Rossi<br>S.r.l.</p>', 'Luigi Rossi'),
            '',
        )

    def test_a_newsletter_gives_nothing(self):
        self.assertEqual(
            company_from_signature(
                '<p>Our latest offers are here!<br>Unsubscribe at any time.</p>'
            ),
            '',
        )

    def test_nothing_to_find_gives_nothing(self):
        self.assertEqual(company_from_signature('', 'Luigi Rossi'), '')


class InternalEmailTests(TestCase):
    def test_our_own_domain_is_internal(self):
        self.assertTrue(is_internal_email('commerxxxx.ricambixxxx@corimetal.it'))
        self.assertTrue(is_internal_email('Andrea@CORIMETAL.IT'))
        self.assertTrue(is_internal_email('someone@mail.corimetal.it'))

    def test_a_client_domain_is_not_internal(self):
        self.assertFalse(is_internal_email('luigi@rossimax.it'))


class PhoneFromSignatureTests(TestCase):
    def test_tel_wins_over_mobile(self):
        self.assertEqual(
            phone_from_signature(SIGNATURE),
            '+390113983511',
        )

    def test_mobile_is_used_when_there_is_no_tel(self):
        self.assertEqual(
            phone_from_signature('<div>Mobile +39 331 403 75 68</div>'),
            '+393314037568',
        )

    def test_a_labelled_number_is_found_in_a_supplier_signature(self):
        self.assertEqual(
            phone_from_signature(SUPPLIER_SIGNATURE),
            '+17135550142',
        )

    def test_tel_must_be_a_whole_word(self):
        # "Hotel" is not a Tel label, and nothing here is labelled at all.
        self.assertEqual(
            phone_from_signature('<p>Hotel reservations<br>+39 02 1234567</p>'),
            '',
        )

    def test_an_unlabelled_number_is_not_a_phone_number(self):
        # A real signature saved us here: the first free-standing number in one
        # is usually the zip code, and "202608" was stored as a phone number.
        self.assertEqual(
            phone_from_signature('<p>Marco Rossi<br>20122 Milano<br>+39 02 1234567</p>'),
            '',
        )

    def test_nothing_to_find_gives_nothing(self):
        self.assertEqual(phone_from_signature('<p>Buongiorno, a presto.</p>'), '')
        self.assertEqual(phone_from_signature(''), '')

    def test_short_numbers_are_not_phone_numbers(self):
        self.assertEqual(phone_from_signature('<p>Ref. 12345</p>'), '')
        self.assertEqual(phone_from_signature('<p>Tel: 202608</p>'), '')


class UpsertContactFromEmailTests(TestCase):
    def test_company_comes_from_the_signature_and_the_phone_too(self):
        contact, created = upsert_contact_from_email(
            email='mcolon@optimanufacturing.com',
            sender_name='Marilyn Colon',
            body=SUPPLIER_SIGNATURE,
        )

        self.assertTrue(created)
        self.assertEqual(contact.company_name, 'Opti Manufacturing Inc.')
        self.assertEqual(contact.contact_person, 'Marilyn Colon')
        self.assertEqual(contact.phone, '+17135550142')

    def test_without_a_signature_the_domain_is_formatted(self):
        contact, created = upsert_contact_from_email(
            email='communicationsit@express.dhl.com',
            sender_name='DHL Express',
            body='<p>Your parcel is on its way.</p>',
        )

        self.assertTrue(created)
        self.assertEqual(contact.company_name, 'DHL')
        self.assertEqual(contact.phone, '')

    def test_the_person_name_is_not_used_as_the_company(self):
        # A signature states the person and then the company; the two must not
        # be swapped, whichever order the sender wrote them in.
        contact, _ = upsert_contact_from_email(
            email='akiss@rossimax.it',
            sender_name='Kiss, Andrea',
            body=SIGNATURE,
        )

        self.assertEqual(contact.company_name, 'Co.Ri.Metal S.R.L.')
        self.assertEqual(contact.contact_person, 'Kiss, Andrea')

    def test_a_contact_with_no_phone_stays_empty(self):
        contact, _ = upsert_contact_from_email(
            email='news@mailing.knf.com',
            sender_name='KNF News',
            body='<p>Read the latest product news.</p>',
        )

        self.assertEqual(contact.phone, '')
        self.assertEqual(contact.company_name, 'KNF')

    def test_our_own_addresses_never_become_contacts(self):
        contact, created = upsert_contact_from_email(
            email='commerxxxx.ricambixxxx@corimetal.it',
            sender_name='Andrea Kiss',
            body=SIGNATURE,
        )

        self.assertIsNone(contact)
        self.assertFalse(created)
        self.assertEqual(Contact.objects.count(), 0)

    def test_the_same_person_is_one_contact_however_the_address_is_cased(self):
        first, _ = upsert_contact_from_email(
            email='Luigi@RossiMax.it',
            sender_name='Luigi Rossi',
        )
        second, created = upsert_contact_from_email(
            email='luigi@rossimax.it',
            sender_name='Luigi Rossi',
        )

        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Contact.objects.count(), 1)

    def test_a_stored_phone_is_never_overwritten(self):
        contact = Contact.objects.create(
            email='luigi@rossimax.it',
            company_name='rossimax',
            phone='+39 111 2223333',
        )

        upsert_contact_from_email(
            email='luigi@rossimax.it',
            body=SIGNATURE,
        )

        contact.refresh_from_db()
        self.assertEqual(contact.phone, '+39 111 2223333')

    def test_a_missing_phone_is_filled_in_from_a_later_message(self):
        contact, _ = upsert_contact_from_email(email='luigi@rossimax.it')

        upsert_contact_from_email(
            email='luigi@rossimax.it',
            body=SIGNATURE,
        )

        contact.refresh_from_db()
        self.assertEqual(contact.phone, '+390113983511')

    def test_an_existing_company_name_is_left_alone(self):
        contact = Contact.objects.create(
            email='luigi@rossimax.it',
            company_name='RossiMax Italia SRL',
        )

        upsert_contact_from_email(
            email='luigi@rossimax.it',
            sender_name='Luigi Rossi',
        )

        contact.refresh_from_db()
        self.assertEqual(contact.company_name, 'RossiMax Italia SRL')
        self.assertEqual(contact.contact_person, 'Luigi Rossi')


class ContactSerializerTests(TestCase):
    def test_the_same_address_cannot_be_added_twice_in_another_case(self):
        Contact.objects.create(email='luigi@rossimax.it', company_name='rossimax')

        serializer = ContactSerializer(data={
            'company_name': 'RossiMax',
            'email': 'Luigi@RossiMax.it',
        })

        self.assertFalse(serializer.is_valid())
        self.assertIn('email', serializer.errors)

    def test_editing_a_contact_may_keep_its_own_address(self):
        contact = Contact.objects.create(
            email='luigi@rossimax.it',
            company_name='rossimax',
        )

        serializer = ContactSerializer(contact, data={
            'company_name': 'RossiMax Italia SRL',
            'email': 'luigi@rossimax.it',
        }, partial=True)

        self.assertTrue(serializer.is_valid(), serializer.errors)
